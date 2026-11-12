"""Optional client for Studio, an MCP server that renders HTML to print-ready PDF.

Sprout builds the HTML from its own templates (validated numbers and options only; never a child's
name, which Sprout stamps onto the PDF afterwards) and keeps the PDF it gets back. Studio is reached
at STUDIO_URL with a personal access token (STUDIO_TOKEN); without STUDIO_URL the Studio-backed
worksheet kinds are hidden. Errors are ``StudioError`` with a message safe to show to families;
Studio's own error text is logged, never shown.
"""

from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

PROTOCOL = "2025-06-18"
UNAVAILABLE = "Studio is busy or unavailable. Try again in a minute."


class StudioError(Exception):
    """Rendering through Studio failed; the message is safe to show."""


class Studio:
    def __init__(
        self,
        url: str,
        token: str,
        http: httpx.AsyncClient,
        *,
        timeout: float = 90,
        max_bytes: int = 20 * 1024 * 1024,
    ):
        self.base = url.rstrip("/")
        self.token, self.http, self.timeout, self.max_bytes = token, http, timeout, max_bytes

    @property
    def configured(self) -> bool:
        return bool(self.base and self.token)

    async def html_to_pdf(self, html: str, *, page_size: str = "letter") -> bytes:
        """Render ``html`` and return the PDF bytes."""
        if not self.configured:
            raise StudioError("Studio is not set up on this server.")
        deadline = time.monotonic() + self.timeout
        try:
            session = await self._initialize()
            try:
                result = await self._call(session, "html_to_pdf", {"html": html, "page_size": page_size})
                while result.get("status") == "pending":
                    if time.monotonic() > deadline:
                        raise StudioError(UNAVAILABLE)
                    result = await self._call(session, "get_job", {"job_id": result["job_id"]})
                if result.get("status") == "failed":
                    log.warning("studio job failed: %s", str(result.get("error"))[:300])
                    raise StudioError("Studio could not make this sheet.")
                return await self._download(str(result["url"]))
            finally:
                await self._close(session)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
            log.warning("studio request failed: %s", type(e).__name__)
            raise StudioError(UNAVAILABLE) from None

    # -- MCP over Streamable HTTP ------------------------------------------------------------------

    def _headers(self, session: str | None = None) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if session:
            h["Mcp-Session-Id"] = session
        return h

    async def _post(self, body: dict, session: str | None) -> httpx.Response:
        r = await self.http.post(self.base + "/mcp", json=body, headers=self._headers(session), timeout=60)
        if r.status_code in (401, 403):
            log.warning("studio refused the token (HTTP %d)", r.status_code)
            raise StudioError("Studio refused Sprout's access token.")
        r.raise_for_status()
        return r

    @staticmethod
    def _message(r: httpx.Response, rid: int) -> dict:
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    msg = json.loads(line[5:].strip())
                    if msg.get("id") == rid:
                        return msg
            raise ValueError("no response in the event stream")
        return r.json()

    async def _initialize(self) -> str | None:
        r = await self._post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "sprout", "version": "1"},
                },
            },
            None,
        )
        msg = self._message(r, 1)
        if "error" in msg:
            raise ValueError("initialize failed")
        session = r.headers.get("mcp-session-id")
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
        return session

    async def _call(self, session: str | None, tool: str, args: dict) -> dict:
        r = await self._post(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": args}},
            session,
        )
        msg = self._message(r, 2)
        if "error" in msg:
            log.warning("studio %s: protocol error %s", tool, str(msg["error"])[:300])
            raise StudioError("Studio could not make this sheet.")
        result = msg["result"]
        if result.get("isError"):
            text = " ".join(c.get("text", "") for c in result.get("content", []))
            log.warning("studio %s refused: %s", tool, text[:300])
            raise StudioError("Studio could not make this sheet.")
        data = result.get("structuredContent")
        if data is None:
            data = json.loads(result["content"][0]["text"])
        return data

    async def _close(self, session: str | None) -> None:
        if not session:
            return
        try:
            await self.http.delete(self.base + "/mcp", headers=self._headers(session), timeout=10)
        except httpx.HTTPError:
            pass

    async def _download(self, url: str) -> bytes:
        # Studio signs links with its public address; fetch the same path from STUDIO_URL.
        path = urlsplit(url).path
        if not path.startswith("/a/") or "/" in path[3:] or ".." in path:
            raise ValueError("unexpected download link")
        r = await self.http.get(self.base + path, timeout=60)
        r.raise_for_status()
        if len(r.content) > self.max_bytes or not r.content.startswith(b"%PDF-"):
            raise ValueError("not a PDF")
        return r.content
