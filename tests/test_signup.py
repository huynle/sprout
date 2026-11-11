import pytest
from conftest import ADMIN, client_as, csrf, png_bytes
from starlette.testclient import TestClient


@pytest.fixture
def open_app(make_app):
    return make_app(signup="open", operator_name="Example Org", contact_email="help@example.com")


def create_family(c, name="Garcia Family"):
    return c.post("/welcome", data={"csrf": csrf(c, "/welcome"), "name": name, "agree": "on"})


def test_open_signup_creates_own_family_and_invites_partner(open_app):
    c = client_as(open_app, "parent@example.com")
    assert c.get("/").headers["location"] == "/welcome"
    assert create_family(c).status_code == 303
    fid = open_app.families.of("parent@example.com")[0]["id"]
    assert open_app.families.role(fid, "parent@example.com") == "owner"
    c.post(
        "/family",
        data={"csrf": csrf(c, "/family"), "action": "add_child", "name": "Ana", "born": "2021-02-03"},
    )
    c.post(
        "/family",
        data={
            "csrf": csrf(c, "/family"),
            "action": "invite",
            "email": "partner@example.com",
            "role": "owner",
        },
    )
    p = client_as(open_app, "partner@example.com")
    assert "Ana" in p.get("/").text  # partner shares the same children and records


def test_terms_must_be_accepted(open_app):
    c = client_as(open_app, "x@example.com")
    r = c.post("/welcome", data={"csrf": csrf(c, "/welcome"), "name": "F"})
    assert "accept the terms" in r.text
    assert not open_app.families.of("x@example.com")


def test_one_family_per_person(open_app):
    c = client_as(open_app, "p@example.com")
    create_family(c)
    r = c.post("/welcome", data={"csrf": csrf(c, "/"), "name": "Second", "agree": "on"})
    assert r.status_code == 403
    assert len(open_app.families.of("p@example.com")) == 1


def test_invite_mode_still_refuses_strangers(app):
    c = TestClient(app.asgi(), follow_redirects=False)
    assert c.get("/dev-login?as=stranger@example.com").status_code == 403


def test_open_signup_needs_operator_details(tmp_path):
    from sprout.config import Settings

    with pytest.raises(RuntimeError, match="OPERATOR"):
        Settings(data_dir=tmp_path, admins=(ADMIN,), dev_login_email=ADMIN, signup="open").check()


def test_policy_pages_are_public(open_app):
    c = TestClient(open_app.asgi(), follow_redirects=False)
    for path in ("/privacy", "/terms"):
        r = c.get(path)
        assert r.status_code == 200 and "Example Org" in r.text and "help@example.com" in r.text


def test_member_leaves(open_app):
    o = client_as(open_app, "o@example.com")
    create_family(o)
    o.post("/family", data={"csrf": csrf(o, "/family"), "action": "invite", "email": "m@example.com"})
    m = client_as(open_app, "m@example.com")
    r = m.post("/family", data={"csrf": csrf(m, "/family"), "action": "leave"})
    assert r.status_code == 303
    assert not open_app.families.of("m@example.com")
    # the sole owner can't leave
    r = o.post("/family", data={"csrf": csrf(o, "/family"), "action": "leave"})
    assert "at least one owner" in r.text


def test_owner_deletes_family_and_files(open_app):
    o = client_as(open_app, "o@example.com")
    create_family(o, "Del Family")
    fid = open_app.families.of("o@example.com")[0]["id"]
    t = csrf(o, "/coloring")
    o.post(
        "/coloring",
        data={"csrf": t, "action": "upload", "title": "c"},
        files={"file": ("c.png", png_bytes(), "image/png")},
    )
    folder = open_app.files.root / str(fid)
    assert folder.exists()
    r = o.post("/family", data={"csrf": t, "action": "delete_family", "confirm": "wrong"})
    assert "exactly" in r.text and open_app.families.get(fid)
    r = o.post("/family", data={"csrf": t, "action": "delete_family", "confirm": "Del Family"})
    assert r.status_code == 303
    assert open_app.families.get(fid) is None and not folder.exists()
    assert open_app.db.one("SELECT COUNT(*) FROM coloring WHERE family_id=?", (fid,))[0] == 0
    # the owner may now start a new family
    assert create_family(o, "Fresh").status_code == 303


def test_members_cannot_delete(open_app):
    o = client_as(open_app, "o@example.com")
    create_family(o, "F1")
    o.post("/family", data={"csrf": csrf(o, "/family"), "action": "invite", "email": "m@example.com"})
    m = client_as(open_app, "m@example.com")
    r = m.post("/family", data={"csrf": csrf(m, "/family"), "action": "delete_family", "confirm": "F1"})
    assert r.status_code == 403


def test_storage_quota(make_app):
    a = make_app(family_quota_bytes=8_000)
    c = client_as(a, ADMIN)
    c.post("/welcome", data={"csrf": csrf(c, "/welcome"), "name": "Q", "agree": "on"})
    t = csrf(c, "/make/math_drill")
    codes = [c.post("/make/math_drill", data={"csrf": t, "count": "20"}).status_code for _ in range(6)]
    assert 413 in codes


def test_instance_ai_cap(make_app, upstream):
    a = make_app(ai_instance_daily_cap=1)
    c = client_as(a, ADMIN)
    c.post("/welcome", data={"csrf": csrf(c, "/welcome"), "name": "Q", "agree": "on"})
    for _ in range(2):
        c.post("/ask", data={"csrf": csrf(c, "/ask"), "text": "x"})
    r = c.post("/ask", data={"csrf": csrf(c, "/ask"), "text": "x"})
    assert "a lot of requests" in r.text.replace("&#39;", "'")
