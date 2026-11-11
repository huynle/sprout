from conftest import ADMIN, client_as, csrf


def test_strangers_are_refused(app):
    from starlette.testclient import TestClient

    c = TestClient(app.asgi(), follow_redirects=False)
    r = c.get("/dev-login?as=stranger@example.com")
    assert r.status_code == 403 and "invite-only" in r.text
    assert c.get("/").status_code == 303  # still not signed in


def test_admin_without_family_goes_to_welcome(app):
    c = client_as(app, ADMIN)
    assert c.get("/").headers["location"] == "/welcome"


def test_invite_then_member_joins_and_sees_family(app, family):
    owner, fid, kids = family
    r = owner.post(
        "/family",
        data={
            "csrf": csrf(owner, "/family"),
            "action": "invite",
            "email": "Parent2@Example.com",
            "role": "member",
        },
    )
    assert r.status_code == 303
    m = client_as(app, "parent2@example.com")
    home = m.get("/").text
    assert "Sam" in home and "Lea" in home
    assert app.families.role(fid, "parent2@example.com") == "member"
    # members can't manage the family
    r = m.post("/family", data={"csrf": csrf(m, "/family"), "action": "invite", "email": "x@example.com"})
    assert r.status_code == 403


def test_removed_member_loses_access_immediately(app, family):
    owner, fid, kids = family
    owner.post(
        "/family",
        data={
            "csrf": csrf(owner, "/family"),
            "action": "invite",
            "email": "p2@example.com",
            "role": "member",
        },
    )
    m = client_as(app, "p2@example.com")
    assert m.get(f"/child/{kids[0]}").status_code == 200
    owner.post(
        "/family", data={"csrf": csrf(owner, "/family"), "action": "remove_member", "email": "p2@example.com"}
    )
    r = m.get(f"/child/{kids[0]}")
    assert r.status_code == 303


def test_last_owner_cannot_leave(app, family):
    owner, fid, kids = family
    r = owner.post(
        "/family", data={"csrf": csrf(owner, "/family"), "action": "remove_member", "email": ADMIN}
    )
    assert "at least one owner" in r.text


def test_ages_shown_not_birthdays(app, family):
    owner, fid, kids = family
    home = owner.get("/").text
    assert "2019-05-01" not in home and " y " in home
