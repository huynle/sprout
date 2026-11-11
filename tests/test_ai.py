import html
import json

from conftest import csrf, png_bytes


class Page:
    def __init__(self, r):
        self.status_code, self.headers, self.text = r.status_code, r.headers, html.unescape(r.text)


def ask(c, kid, text):
    return Page(c.post("/ask", data={"csrf": csrf(c, "/ask"), "child_id": kid, "text": text}))


def test_sheet_plan_becomes_draft(app, family, upstream):
    c, fid, kids = family
    upstream.chat_reply = {
        "action": "sheet",
        "kind": "math_drill",
        "params": {"ops": "add", "digits": 2, "count": 20},
        "note": "Big print",
    }
    r = ask(c, kids[0], "20 two-digit addition problems")
    assert r.status_code == 303 and "from=ask" in r.headers["location"]
    s = app.db.one("SELECT * FROM sheets WHERE family_id=?", (fid,))
    assert s["status"] == "draft" and s["source"] == "ai" and json.loads(s["params"])["digits"] == 2


def test_model_gets_minimum_child_data(app, family, upstream):
    c, fid, kids = family
    upstream.chat_reply = {"action": "cannot", "message": "Try a math sheet"}
    ask(c, kids[0], "something")
    body = json.loads(upstream.calls[-1].content)
    user = body["messages"][1]["content"]
    assert "Sam" in user and "age " in user and "2019" not in user


def test_invalid_params_are_refused(app, family, upstream):
    c, fid, kids = family
    upstream.chat_reply = {"action": "sheet", "kind": "math_drill", "params": {"count": 999, "evil": "x"}}
    r = ask(c, kids[0], "lots")
    assert r.status_code == 200 and "didn't fit" in r.text
    assert app.db.one("SELECT COUNT(*) FROM sheets")[0] == 0


def test_unknown_action_and_html_are_refused(app, family, upstream):
    c, fid, kids = family
    upstream.chat_reply = {"action": "html", "html": "<script>alert(1)</script>"}
    r = ask(c, kids[0], "make a web page")
    assert "didn't fit" in r.text and "<script>alert" not in r.text


def test_garbage_reply(app, family, upstream):
    c, fid, kids = family
    upstream.chat_reply = "I am not JSON"
    r = ask(c, kids[0], "hi")
    assert "couldn't be reached" in r.text


def test_coloring_drawn(app, family, upstream):
    c, fid, kids = family
    upstream.chat_reply = {"action": "coloring", "prompt": "a small airplane over hills", "title": "Airplane"}
    upstream.image_png = png_bytes(1024, 1024)
    r = ask(c, kids[0], "a coloring page with a plane")
    assert r.status_code == 303
    img_call = [x for x in upstream.calls if x.url.path.endswith("/images/generations")][0]
    assert "coloring page" in json.loads(img_call.content)["prompt"]


def test_cannot_message_shown(app, family, upstream):
    c, fid, kids = family
    upstream.chat_reply = {"action": "cannot", "message": "I can make math or tracing sheets."}
    assert "math or tracing" in ask(c, kids[0], "teach calculus").text


def test_not_configured(make_app, tmp_path):
    from conftest import ADMIN, client_as

    from sprout.config import Settings
    from sprout.web import App

    a = App(Settings(data_dir=tmp_path / "d2", admins=(ADMIN,), dev_login_email=ADMIN))
    c = client_as(a, ADMIN)
    c.post("/welcome", data={"csrf": csrf(c, "/welcome"), "name": "F"})
    assert "isn't set up" in c.get("/ask").text


def test_daily_limit(app, family, upstream, monkeypatch):
    from sprout import ai

    monkeypatch.setattr(ai, "DAILY_LIMIT", 1)
    c, fid, kids = family
    ask(c, kids[0], "one")
    ask(c, kids[0], "two")
    assert "a lot of requests" in ask(c, kids[0], "three").text
