"""Family B must never read or change family A's data, by id guessing or otherwise."""

import pytest
from conftest import ADMIN, client_as, csrf


@pytest.fixture
def two_families(app, family):
    owner_a, fid_a, kids_a = family
    # A makes a sheet, a coloring page, an idea
    t = csrf(owner_a, "/make/math_drill")
    r = owner_a.post("/make/math_drill", data={"csrf": t, "child_id": kids_a[0], "count": "20", "seed": "5"})
    sheet_a = int(r.headers["location"].rsplit("/", 1)[1])
    from conftest import png_bytes

    r = owner_a.post(
        "/coloring",
        data={"csrf": t, "action": "upload", "title": "Cat"},
        files={"file": ("cat.png", png_bytes(), "image/png")},
    )
    page_a = int(r.headers["location"].rsplit("/", 1)[1])
    owner_a.post("/ideas", data={"csrf": t, "action": "add", "title": "Treehouse", "machine": "cnc"})
    idea_a = app.db.one("SELECT id FROM ideas WHERE family_id=?", (fid_a,))["id"]
    # B: a second family run by another owner
    fid_b = app.families.create("Other Family", "b@example.com", ADMIN)
    b = client_as(app, "b@example.com")
    return {
        "a": owner_a,
        "b": b,
        "fid_a": fid_a,
        "fid_b": fid_b,
        "kid_a": kids_a[0],
        "sheet_a": sheet_a,
        "page_a": page_a,
        "idea_a": idea_a,
    }


@pytest.mark.parametrize(
    "path",
    [
        "/child/{kid_a}",
        "/sheet/{sheet_a}",
        "/sheet/{sheet_a}.pdf",
        "/sheet/{sheet_a}/page/0.png",
        "/coloring/{page_a}",
        "/coloring/{page_a}.pdf",
        "/coloring/{page_a}.png",
    ],
)
def test_reads_are_isolated(two_families, path):
    r = two_families["b"].get(path.format(**two_families))
    assert r.status_code == 404


def test_lists_are_isolated(two_families):
    b = two_families["b"]
    for path in ("/", "/coloring", "/ideas", "/ask", "/family"):
        html = b.get(path).text
        assert "Sam" not in html and "Treehouse" not in html and "Cat" not in html, path


def test_writes_are_isolated(app, two_families):
    b, d = two_families["b"], two_families
    t = csrf(b, "/ideas")
    assert b.post(f"/child/{d['kid_a']}", data={"csrf": t, "action": "note", "title": "x"}).status_code == 404
    assert b.post(f"/sheet/{d['sheet_a']}", data={"csrf": t, "action": "keep"}).status_code == 404
    b.post("/ideas", data={"csrf": t, "action": "status", "idea_id": d["idea_a"], "status": "dropped"})
    assert app.db.one("SELECT status FROM ideas WHERE id=?", (d["idea_a"],))["status"] == "idea"
    # B can't attach its log or sheets to A's child
    b.post("/make/math_drill", data={"csrf": t, "child_id": d["kid_a"], "count": "20"})
    assert app.db.one("SELECT COUNT(*) FROM sheets WHERE family_id=?", (d["fid_b"],))[0] == 0
    # B can't switch into A's family
    assert b.post("/family/switch", data={"csrf": t, "family_id": d["fid_a"]}).status_code == 403


def test_files_are_namespaced(app, two_families):
    from sprout.store import NotFound, Store

    row = app.db.one("SELECT file FROM sheets WHERE id=?", (two_families["sheet_a"],))
    store_b = Store(app.db, app.files, two_families["fid_b"])
    with pytest.raises(NotFound):
        store_b.file(row["file"])
    with pytest.raises(NotFound):
        store_b.file(f"{two_families['fid_b']}/../{row['file']}")
