"""Studio-backed worksheets: offered only when Studio is set up, rendered over MCP, the child's
name stamped by Sprout (never sent to Studio), daily cap, and safe failures."""

import io
import json

import pytest
from conftest import FakeStudio, csrf
from pypdf import PdfReader

from sprout import sheets
from sprout.worksheets import big_addition


@pytest.fixture
def studio_app(make_app):
    return make_app(studio_url=FakeStudio.BASE, studio_token="imcp_test")


@pytest.fixture
def sfamily(studio_app):
    from conftest import client_as

    c = client_as(studio_app, "admin@example.com")
    c.post("/welcome", data={"csrf": csrf(c, "/welcome"), "name": "Example Family", "agree": "on"})
    fid = studio_app.families.of("admin@example.com")[0]["id"]
    c.post(
        "/family",
        data={"csrf": csrf(c, "/family"), "action": "add_child", "name": "Sam", "born": "2019-05-01"},
    )
    kid = studio_app.db.one("SELECT id FROM children WHERE family_id=?", (fid,))["id"]
    return c, fid, kid


def make_big(c, kid, **extra):
    data = {
        "csrf": csrf(c, "/make/big_addition"),
        "child_id": kid,
        "count": "12",
        "answer_key": "on",
        **extra,
    }
    return c.post("/make/big_addition", data=data)


def text_of(app, sid) -> list[str]:
    from sprout.store import Store

    s = app.db.one("SELECT * FROM sheets WHERE id=?", (sid,))
    st = Store(app.db, app.files, s["family_id"])
    pdf = st.file(s["file"]).read_bytes()
    return [p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages]


def test_hidden_without_studio(app, family):
    c, _, _ = family
    assert "Big addition" not in c.get("/make").text
    assert c.get("/make/big_addition").status_code == 404


def test_render_stamps_name_and_never_sends_it(studio_app, sfamily, upstream):
    c, fid, kid = sfamily
    assert "Big addition" in c.get("/make").text
    r = make_big(c, kid)
    assert r.status_code == 303, r.text
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    pages = text_of(studio_app, sid)
    assert len(pages) == 2 and "Sam" in pages[0] and "Sam" not in pages[1]
    html = upstream.studio.html[0]
    assert "Sam" not in html and "Name:" in html and "answer" in html.lower()
    assert upstream.studio.auth[0] == "Bearer imcp_test"
    s = studio_app.db.one("SELECT * FROM sheets WHERE id=?", (sid,))
    assert s["kind"] == "big_addition" and json.loads(s["params"])["seed"]
    assert s["title"].startswith("Big addition: 12 two-digit problems")


def test_pending_job_and_sse_replies(studio_app, sfamily, upstream):
    c, fid, kid = sfamily
    upstream.studio.sse, upstream.studio.pending = True, 2
    assert make_big(c, kid).status_code == 303


@pytest.mark.parametrize(
    "setup,message",
    [
        (lambda st: setattr(st, "error", "chromium exploded at /tmp/x"), "Studio could not make this sheet"),
        (lambda st: setattr(st, "status", 401), "refused Sprout"),
        (lambda st: setattr(st, "status", 503), "busy or unavailable"),
        (lambda st: setattr(st, "pdf", b"<html>not a pdf"), "busy or unavailable"),
        (lambda st: setattr(st, "link", "https://studio.example/other/../a/x"), "busy or unavailable"),
    ],
)
def test_failures_are_safe_and_store_nothing(studio_app, sfamily, upstream, setup, message):
    c, fid, kid = sfamily
    setup(upstream.studio)
    r = make_big(c, kid)
    assert r.status_code == 200 and message in r.text
    assert "chromium" not in r.text
    assert studio_app.db.one("SELECT COUNT(*) FROM sheets WHERE family_id=?", (fid,))[0] == 0


def test_daily_cap(make_app, upstream):
    from conftest import client_as

    app = make_app(studio_url=FakeStudio.BASE, studio_token="t", studio_family_daily_cap=1)
    c = client_as(app, "admin@example.com")
    c.post("/welcome", data={"csrf": csrf(c, "/welcome"), "name": "F", "agree": "on"})
    assert make_big(c, "").status_code == 303
    r = make_big(c, "")
    assert r.status_code == 200 and "Try again tomorrow" in r.text
    assert len(upstream.studio.html) == 1


def test_assistant_can_pick_big_addition(studio_app, sfamily, upstream):
    c, fid, kid = sfamily
    upstream.chat_reply = {"action": "sheet", "kind": "big_addition", "params": {"count": 8}}
    r = c.post("/ask", data={"csrf": csrf(c, "/ask"), "child_id": kid, "text": "big addition"})
    assert r.status_code == 303
    s = studio_app.db.one("SELECT * FROM sheets WHERE family_id=?", (fid,))
    assert s["kind"] == "big_addition" and s["source"] == "ai"
    assert "Sam" not in upstream.studio.html[0]
    assert "big_addition" in json.loads(upstream.calls[0].content)["messages"][0]["content"]


def test_assistant_does_not_offer_studio_kinds_without_studio(app, family, upstream):
    c, fid, kids = family
    c.post("/ask", data={"csrf": csrf(c, "/ask"), "child_id": kids[0], "text": "x"})
    assert "big_addition" not in json.loads(upstream.calls[0].content)["messages"][0]["content"]


def test_html_only_numbers_and_name_line():
    html = big_addition.make_html(1111, 12, False, True)
    assert html.count("class='p'") == 24 and "Answer key" in html
    nocarry = big_addition.make_html(5, 16, False, False)
    assert nocarry.count("class='p'") == 16 and "Answer key" not in nocarry


def test_stamp_name_fits_long_names():
    from conftest import letter_pdf

    out = sheets.stamp_name(letter_pdf(1), "Maximiliana-Josephine", big_addition.NAME_LINE)
    assert "Maximiliana-Josephine" in PdfReader(io.BytesIO(out)).pages[0].extract_text()
