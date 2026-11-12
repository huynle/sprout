"""Worksheet kinds. Each kind declares its fields once; the same spec drives the web form,
the validation of AI-produced parameters and the call into the shared generator at the repo root.

Kinds with ``html`` instead of ``render`` are drawn by Studio (``sprout.studio``): they are offered
only when Studio is set up, count against a per-family daily cap, and get the child's name stamped
onto page 1 by Sprout after rendering (the name is never sent to Studio). Callers use ``make``.
"""

from __future__ import annotations

import io
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sprout.studio import Studio, StudioError
from sprout.worksheets import big_addition, math_drill
from sprout.worksheets import name_trace as trace_name


class InvalidParams(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    type: str  # choice | bool | int | text
    default: Any = None
    choices: tuple = ()  # (value, label) pairs for choice
    help: str = ""
    min: int | None = None
    max: int | None = None
    max_len: int = 40


@dataclass(frozen=True)
class Kind:
    id: str
    label: str
    description: str
    fields: tuple[Field, ...]
    render: Callable[[dict], tuple[str, bytes]] | None = None
    ages: str = ""
    extra: dict = field(default_factory=dict)
    # Studio kinds: params -> (title, html, name_line); see big_addition.NAME_LINE
    html: Callable[[dict], tuple[str, str, dict]] | None = None

    @property
    def studio(self) -> bool:
        return self.html is not None

    def validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Coerce and check raw values (form strings or JSON); unknown keys are refused."""
        unknown = set(raw) - {f.name for f in self.fields}
        if unknown:
            raise InvalidParams(f"unknown fields: {', '.join(sorted(unknown))}")
        out: dict[str, Any] = {}
        for f in self.fields:
            v = raw.get(f.name)
            if v in (None, ""):
                if f.type == "bool" and f.name in raw:
                    v = False
                elif f.type == "text" and f.default is None:
                    raise InvalidParams(f"{f.label}: required")
                else:
                    out[f.name] = f.default
                    continue
            if f.type == "choice":
                allowed = {str(c[0]): c[0] for c in f.choices}
                if str(v) not in allowed:
                    raise InvalidParams(f"{f.label}: choose one of {', '.join(allowed)}")
                out[f.name] = allowed[str(v)]
            elif f.type == "bool":
                out[f.name] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")
            elif f.type == "int":
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    raise InvalidParams(f"{f.label}: must be a whole number") from None
                if (f.min is not None and n < f.min) or (f.max is not None and n > f.max):
                    raise InvalidParams(f"{f.label}: must be between {f.min} and {f.max}")
                out[f.name] = n
            elif f.type == "text":
                s = str(v).strip()
                if not s or len(s) > f.max_len or any(ord(ch) < 32 for ch in s):
                    raise InvalidParams(f"{f.label}: 1 to {f.max_len} plain characters")
                out[f.name] = s
        return out

    def json_schema(self) -> dict:
        props = {}
        for f in self.fields:
            if f.type == "choice":
                props[f.name] = {"enum": [c[0] for c in f.choices], "description": f.help or f.label}
            elif f.type == "bool":
                props[f.name] = {"type": "boolean", "description": f.help or f.label}
            elif f.type == "int":
                props[f.name] = {
                    "type": "integer",
                    "minimum": f.min,
                    "maximum": f.max,
                    "description": f.help or f.label,
                }
            else:
                props[f.name] = {"type": "string", "maxLength": f.max_len, "description": f.help or f.label}
        return {"type": "object", "properties": props, "additionalProperties": False}


def _render_math(p: dict) -> tuple[str, bytes]:
    seed = p["seed"] or random.randint(1, 10**6)
    p["seed"] = seed
    pdf = math_drill.make_math_drill(seed, p["ops"], p["digits"], p["regroup"], p["count"], p["answer_key"])
    digits = "2-digit" if p["digits"] == 2 else "1-digit"
    regroup = " with carrying" if p["digits"] == 2 and p["regroup"] else ""
    return f"{math_drill.title_for(p['ops'])}: {p['count']} {digits}{regroup}", pdf


def _render_trace(p: dict) -> tuple[str, bytes]:
    try:
        pdf = trace_name.make_name_trace(p["name"], p["size"])
    except ValueError as e:
        raise InvalidParams(str(e)) from None
    size = {88: "big", 60: "medium", 36: "small", 28: "smaller"}.get(p["size"], f"{p['size']}pt")
    return f"Trace my name: {p['name']} ({size})", pdf


def _html_big_addition(p: dict) -> tuple[str, str, dict]:
    seed = p["seed"] or random.randint(1, 10**6)
    p["seed"] = seed
    html = big_addition.make_html(seed, p["count"], p["regroup"], p["answer_key"])
    carry = " with carrying" if p["regroup"] else ""
    return f"Big addition: {p['count']} two-digit problems{carry}", html, big_addition.NAME_LINE


KINDS: dict[str, Kind] = {
    "math_drill": Kind(
        id="math_drill",
        label="Math drill",
        description="Vertical addition and subtraction with an answer key on page 2.",
        ages="5+",
        fields=(
            Field(
                "ops",
                "Problems",
                "choice",
                "mixed",
                (
                    ("mixed", "Addition and subtraction"),
                    ("add", "Addition only"),
                    ("sub", "Subtraction only"),
                ),
            ),
            Field("digits", "Numbers", "choice", 1, ((1, "1 digit (up to 18)"), (2, "2 digits"))),
            Field("regroup", "Carrying / borrowing (2 digits only)", "bool", False),
            Field(
                "count",
                "How many problems",
                "choice",
                60,
                ((20, "20 (big print)"), (30, "30 (big print)"), (40, "40"), (60, "60")),
            ),
            Field("answer_key", "Add answer key page", "bool", True),
            Field(
                "seed",
                "Seed (leave empty for new problems)",
                "int",
                None,
                min=1,
                max=10**9,
                help="same seed = same problems; omit for new ones",
            ),
        ),
        render=_render_math,
    ),
    "name_trace": Kind(
        id="name_trace",
        label="Name tracing",
        description="Trace a name with single-stroke letters, green start dots and stroke order.",
        ages="3-6",
        fields=(
            Field(
                "name",
                "Name or word (exact case)",
                "text",
                None,
                help="letters defined so far: " + " ".join(sorted(trace_name.LETTERS)),
                max_len=20,
            ),
            Field(
                "size",
                "Letter size",
                "choice",
                88,
                ((88, "Big"), (60, "Medium"), (36, "Small"), (28, "Smaller")),
            ),
        ),
        render=_render_trace,
        extra={"letters": "".join(sorted(trace_name.LETTERS))},
    ),
}


KINDS["big_addition"] = Kind(
    id="big_addition",
    label="Big addition",
    description="Large two-digit addition problems with lots of room, laid out by Studio.",
    ages="5+",
    fields=(
        Field("count", "How many problems", "choice", 12, ((8, "8"), (12, "12"), (16, "16"))),
        Field("regroup", "Carrying", "bool", False),
        Field("answer_key", "Add answer key page", "bool", True),
        Field(
            "seed",
            "Seed (leave empty for new problems)",
            "int",
            None,
            min=1,
            max=10**9,
            help="same seed = same problems; omit for new ones",
        ),
    ),
    html=_html_big_addition,
)

STUDIO_KINDS = tuple(k.id for k in KINDS.values() if k.studio)


def available(studio: Studio | None) -> dict[str, Kind]:
    """The kinds this server can make (Studio kinds only when Studio is set up)."""
    ok = bool(studio and studio.configured)
    return {k: v for k, v in KINDS.items() if ok or not v.studio}


def stamp_name(pdf: bytes, name: str, line: dict) -> bytes:
    """Write ``name`` on the name line of page 1 (``line``: x, y, width in inches from top-left)."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.units import inch
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    writer = PdfWriter(clone_from=io.BytesIO(pdf))
    first = writer.pages[0]
    w, h = float(first.mediabox.width), float(first.mediabox.height)
    size = 18.0
    while size > 8 and stringWidth(name, "Helvetica", size) > line["width"] * inch - 8:
        size -= 1
    overlay = io.BytesIO()
    c = canvas.Canvas(overlay, pagesize=(w, h))
    c.setFont("Helvetica", size)
    c.drawString(line["x"] * inch + 6, h - line["y"] * inch + 5, name)
    c.save()
    first.merge_page(PdfReader(io.BytesIO(overlay.getvalue())).pages[0])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


async def make(
    kind: Kind,
    params: dict,
    *,
    studio: Studio | None = None,
    child: dict | None = None,
    renders_today: int = 0,
    daily_cap: int = 0,
) -> tuple[str, bytes]:
    """Make a sheet of ``kind`` (params already validated). ``InvalidParams`` for anything the
    family can act on: Studio not set up, the daily cap, or Studio failing."""
    if not kind.studio:
        return kind.render(params)
    if not (studio and studio.configured):
        raise InvalidParams(f"{kind.label} isn't available on this server")
    if renders_today >= daily_cap:
        raise InvalidParams(f"That's a lot of {kind.label} sheets today. Try again tomorrow.")
    title, html, line = kind.html(params)
    try:
        pdf = await studio.html_to_pdf(html)
    except StudioError as e:
        raise InvalidParams(str(e)) from None
    if child and child.get("name"):
        pdf = stamp_name(pdf, str(child["name"])[:40], line)
    return title, pdf


def preview_png(pdf: bytes, page: int = 0, width: int = 900) -> bytes:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    try:
        pg = doc[min(page, len(doc) - 1)]
        scale = width / pg.get_width()
        img = pg.render(scale=scale).to_pil()
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    finally:
        doc.close()


def page_count(pdf: bytes) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    try:
        return len(doc)
    finally:
        doc.close()
