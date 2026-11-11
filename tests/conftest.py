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
        if url in self.files:
            status, body = self.files[url]
            return httpx.Response(status, content=body)
        return httpx.Response(404)


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
