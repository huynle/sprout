import json
import re
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from sprout.config import Settings
from sprout.web import App

ADMIN = "admin@example.com"


class FakeUpstream:
    """Stands in for the LLM API and coloring sites; records requests; never touches the network."""

    def __init__(self):
        self.calls = []
        self.chat_reply: dict | str = {"action": "cannot", "message": "nope"}
        self.image_png = None
        self.files: dict[str, tuple[int, bytes]] = {}
        self.studio = FakeStudio()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        if url.endswith("/chat/completions"):
            content = self.chat_reply if isinstance(self.chat_reply, str) else json.dumps(self.chat_reply)
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        if url.endswith("/images/generations"):
            import base64

            return httpx.Response(
                200, json={"data": [{"b64_json": base64.b64encode(self.image_png).decode()}]}
            )
        if url.startswith(FakeStudio.BASE):
            return self.studio.handle(request)
        if url in self.files:
            status, body = self.files[url]
            return httpx.Response(status, content=body)
        return httpx.Response(404)


def letter_pdf(pages: int = 2) -> bytes:
    import io

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for i in range(pages):
        c.drawString(72, 700, f"page {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


class FakeStudio:
    """A Streamable HTTP MCP server with html_to_pdf and get_job (JSON and SSE replies)."""

    BASE = "http://studio.test"

    def __init__(self):
        self.html: list[str] = []
        self.pending = 0  # how many get_job polls answer "pending" first
        self.error: str | None = None  # html_to_pdf answers isError with this text
        self.status = 200
        self.sse = False
        self.link = "https://studio.example/a/as_x.123.sig"
        self.pdf = letter_pdf(2)
        self.auth: list[str] = []

    def _reply(self, rid, result, headers=None):
        body = {"jsonrpc": "2.0", "id": rid, "result": result}
        if self.sse:
            return httpx.Response(
                200,
                text=f"event: message\ndata: {json.dumps(body)}\n\n",
                headers={"content-type": "text/event-stream", **(headers or {})},
            )
        return httpx.Response(200, json=body, headers=headers or {})

    def _done(self):
        return {"structuredContent": {"status": "done", "asset_id": "as_x", "url": self.link}, "content": []}

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.startswith("/a/"):
            return httpx.Response(200, content=self.pdf, headers={"content-type": "application/pdf"})
        if request.method == "DELETE":
            return httpx.Response(200)
        self.auth.append(request.headers.get("authorization", ""))
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "invalid_token"})
        msg = json.loads(request.content)
        method = msg.get("method")
        if method == "initialize":
            return self._reply(msg["id"], {"protocolVersion": "2025-06-18"}, {"mcp-session-id": "s1"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        name, args = msg["params"]["name"], msg["params"]["arguments"]
        if name == "html_to_pdf":
            self.html.append(args["html"])
            if self.error:
                return self._reply(
                    msg["id"], {"isError": True, "content": [{"type": "text", "text": self.error}]}
                )
            if self.pending:
                return self._reply(msg["id"], {"structuredContent": {"status": "pending", "job_id": "j1"}})
            return self._reply(msg["id"], self._done())
        if name == "get_job":
            self.pending -= 1
            if self.pending > 0:
                return self._reply(msg["id"], {"structuredContent": {"status": "pending", "job_id": "j1"}})
            return self._reply(msg["id"], self._done())
        return httpx.Response(400)


def png_bytes(w=300, h=400) -> bytes:
    import io

    from PIL import Image, ImageDraw

    im = Image.new("RGB", (w, h), "white")
    ImageDraw.Draw(im).ellipse([20, 20, w - 20, h - 20], outline="black", width=8)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def upstream():
    return FakeUpstream()


@pytest.fixture
def make_app(tmp_path: Path, upstream):
    def make(**kw):
        s = Settings(
            data_dir=tmp_path / "data",
            admins=(ADMIN,),
            dev_login_email=ADMIN,
            llm_url="https://llm.test/v1",
            llm_key="k",
            llm_model="m",
            image_model="img",
            **kw,
        )
        return App(s, http=httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler)))

    return make


@pytest.fixture
def app(make_app):
    return make_app()


def client_as(app: App, email: str) -> TestClient:
    c = TestClient(app.asgi(), follow_redirects=False)
    r = c.get(f"/dev-login?as={email}")
    assert r.status_code == 303, r.text
    return c


def csrf(client: TestClient, path: str = "/") -> str:
    html = client.get(path).text
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, html[:500]
    return m.group(1)


@pytest.fixture
def family(app):
    """An admin-created family with two children; returns (client_for_owner, family_id, child_ids)."""
    c = client_as(app, ADMIN)
    r = c.post("/welcome", data={"csrf": csrf(c, "/welcome"), "name": "Example Family", "agree": "on"})
    assert r.status_code == 303
    fid = app.families.of(ADMIN)[0]["id"]
    t = csrf(c, "/family")
    for name, born in (("Sam", "2019-05-01"), ("Lea", "2022-09-30")):
        r = c.post("/family", data={"csrf": t, "action": "add_child", "name": name, "born": born})
        assert r.status_code == 303, r.text
    kids = [k["id"] for k in app.db.q("SELECT id FROM children WHERE family_id=? ORDER BY id", (fid,))]
    return c, fid, kids
