import re

from conftest import ADMIN, client_as, csrf, png_bytes


def test_csrf_and_origin_required(family):
    c, fid, kids = family
    assert c.post("/ideas", data={"action": "add", "title": "x"}).status_code == 403
    t = csrf(c, "/ideas")
    r = c.post(
        "/ideas", data={"csrf": t, "action": "add", "title": "x"}, headers={"Origin": "https://evil.test"}
    )
    assert r.status_code == 403


def test_security_headers(family):
    c, *_ = family
    r = c.get("/")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in r.headers["cache-control"]


def test_make_math_preview_keep_and_log(app, family):
    c, fid, kids = family
    t = csrf(c, "/make/math_drill")
    r = c.post(
        "/make/math_drill",
        data={"csrf": t, "child_id": kids[0], "ops": "add", "digits": "2", "count": "30", "answer_key": "on"},
    )
    assert r.status_code == 303
    loc = r.headers["location"]
    page = c.get(loc).text
    assert "draft" in page and "Addition Practice" in page and "2 pages" in page
    assert c.get(loc + ".pdf").content.startswith(b"%PDF-")
    assert c.get(loc + "/page/0.png").content.startswith(b"\x89PNG")
    c.post(loc, data={"csrf": t, "action": "keep"})
    hist = c.get(f"/child/{kids[0]}").text
    assert "Addition Practice" in hist


def test_bad_params_show_error(family):
    c, fid, kids = family
    t = csrf(c, "/make/math_drill")
    r = c.post("/make/math_drill", data={"csrf": t, "count": "17"})
    assert r.status_code == 200 and "choose one of" in r.text


def test_name_trace_prefills_child_name(app, family):
    c, fid, kids = family
    html = c.get(f"/make/name_trace?child={kids[0]}").text
    assert 'value="Sam"' in html
    t = csrf(c, "/make/name_trace")
    r = c.post("/make/name_trace", data={"csrf": t, "child_id": kids[0], "name": "Sam", "size": "60"})
    assert r.status_code == 303


def test_feedback_and_plan(app, family):
    c, fid, kids = family
    t = csrf(c, f"/child/{kids[1]}")
    c.post(
        f"/child/{kids[1]}", data={"csrf": t, "action": "feedback", "rating": "too_easy", "detail": "fast!"}
    )
    c.post(
        f"/child/{kids[1]}",
        data={"csrf": t, "action": "plan", "current_level": "Counts to 20", "next_steps": "Count to 50"},
    )
    html = c.get(f"/child/{kids[1]}").text
    assert "Too easy" in html and "fast!" in html and "Counts to 20" in html


def test_coloring_upload_and_log(app, family):
    c, fid, kids = family
    t = csrf(c, "/coloring")
    r = c.post(
        "/coloring",
        data={"csrf": t, "action": "upload", "title": "Plane", "tags": "Planes, Sky"},
        files={"file": ("p.png", png_bytes(500, 300), "image/png")},
    )
    assert r.status_code == 303
    pid = r.headers["location"].rsplit("/", 1)[1]
    assert c.get(f"/coloring/{pid}.pdf").content.startswith(b"%PDF-")
    assert "planes" in c.get("/coloring").text
    c.post(f"/coloring/{pid}", data={"csrf": t, "child_id": kids[0]})
    assert "Coloring: Plane" in c.get(f"/child/{kids[0]}").text


def test_coloring_rejects_junk_and_foreign_urls(app, family, upstream):
    c, fid, kids = family
    t = csrf(c, "/coloring")
    r = c.post(
        "/coloring",
        data={"csrf": t, "action": "upload"},
        files={"file": ("x.png", b"not an image", "image/png")},
    )
    assert "can read" in r.text
    r = c.post("/coloring", data={"csrf": t, "action": "url", "url": "http://169.254.169.254/latest"})
    assert "Only https links" in r.text
    assert not upstream.calls


def test_coloring_url_import(app, family, upstream):
    c, fid, kids = family
    url = "https://cdn.supercoloring.com/x/plane.png"
    upstream.files[url] = (200, png_bytes())
    t = csrf(c, "/coloring")
    r = c.post("/coloring", data={"csrf": t, "action": "url", "url": url, "title": "Plane"})
    assert r.status_code == 303


def test_ideas_board(app, family):
    c, fid, kids = family
    t = csrf(c, "/ideas")
    c.post(
        "/ideas",
        data={"csrf": t, "action": "add", "title": "Bird feeder", "machine": "cnc", "child_id": kids[0]},
    )
    html = c.get("/ideas").text
    assert "Bird feeder" in html and "CNC router" in html
    iid = re.search(r'name="idea_id" value="(\d+)"', html).group(1)
    c.post("/ideas", data={"csrf": t, "action": "status", "idea_id": iid, "status": "built"})
    assert app.db.one("SELECT status FROM ideas WHERE id=?", (iid,))["status"] == "built"


def test_pwa_and_health(app):
    from starlette.testclient import TestClient

    c = TestClient(app.asgi())
    assert c.get("/healthz").json() == {"status": "ok"}
    assert "Sprout" in c.get("/manifest.webmanifest").text
    assert c.get("/sw.js").status_code == 200


def test_dev_login_refused_outside_localhost(tmp_path):
    import pytest

    from sprout.config import Settings

    with pytest.raises(RuntimeError):
        Settings(
            public_base_url="https://sprout.example.com",
            admins=(ADMIN,),
            dev_login_email=ADMIN,
            data_dir=tmp_path,
        ).check()


def test_admin_page_only_for_admins(app, family):
    c, fid, kids = family
    c.post(
        "/family",
        data={"csrf": csrf(c, "/family"), "action": "invite", "email": "m@example.com", "role": "owner"},
    )
    m = client_as(app, "m@example.com")
    assert m.get("/admin").status_code == 404
    assert "Example Family" in c.get("/admin").text
