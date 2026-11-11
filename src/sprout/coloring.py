"""Coloring pages: turn an uploaded or imported image/PDF into a one-page US Letter PDF.

URL import only fetches from ALLOWED_HOSTS over https, follows no redirects to other hosts,
and caps the size. Images are re-encoded (metadata dropped) and fitted to the page.
"""

from __future__ import annotations

import io
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ALLOWED_HOSTS = frozenset({"www.supercoloring.com", "cdn.supercoloring.com", "supercoloring.com"})
Image.MAX_IMAGE_PIXELS = 60_000_000


class ColoringError(ValueError):
    pass


async def fetch_allowed(http: httpx.AsyncClient, url: str, max_bytes: int) -> bytes:
    u = urlparse(url.strip())
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise ColoringError("Only https links from " + ", ".join(sorted(ALLOWED_HOSTS)) + " can be imported.")
    try:
        async with http.stream("GET", url.strip(), follow_redirects=False, timeout=20) as r:
            if r.status_code != 200:
                raise ColoringError(
                    f"The site answered {r.status_code}. Use the link to the image or PDF itself."
                )
            data = b""
            async for chunk in r.aiter_bytes():
                data += chunk
                if len(data) > max_bytes:
                    raise ColoringError("That file is too big.")
            return data
    except httpx.HTTPError:
        raise ColoringError("Couldn't download that link.") from None


def to_pdf(data: bytes, max_bytes: int) -> bytes:
    if len(data) > max_bytes:
        raise ColoringError("That file is too big.")
    if data.startswith(b"%PDF-"):
        return _first_page_pdf(data)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ColoringError("That isn't a picture or PDF Sprout can read (PNG, JPEG, WebP or PDF).") from None
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    return image_page(img)


def image_page(img: Image.Image, title: str = "") -> bytes:
    pw, ph = letter
    margin, top = 36, 36 + (28 if title else 0)
    scale = min((pw - 2 * margin) / img.width, (ph - margin - top) / img.height)
    w, h = img.width * scale, img.height * scale
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    if title:
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(pw / 2, ph - 40, title[:80])
    c.drawImage(ImageReader(img), (pw - w) / 2, margin + (ph - margin - top - h) / 2, w, h)
    c.showPage()
    c.save()
    return buf.getvalue()


def _first_page_pdf(data: bytes) -> bytes:
    """Re-render page 1 as an image page: drops scripts, forms and anything else in the original PDF."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError:
        raise ColoringError("That PDF can't be opened.") from None
    try:
        if len(doc) < 1:
            raise ColoringError("That PDF has no pages.")
        pg = doc[0]
        img = pg.render(scale=200 / 72).to_pil().convert("RGB")
    finally:
        doc.close()
    return image_page(img)
