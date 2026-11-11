import pytest

from sprout.importer import ImportError_, import_data
from sprout.store import Store


def test_import_creates_family_children_log_and_files(app, tmp_path):
    base = tmp_path / "export"
    (base / "sam").mkdir(parents=True)
    from sprout.worksheets.math_drill import make_math_drill

    (base / "sam" / "m.pdf").write_bytes(make_math_drill(1))
    data = {
        "family": {
            "name": "Imported",
            "owners": ["o@example.com", "o2@example.com"],
            "members": ["m@example.com"],
        },
        "children": [
            {
                "key": "sam",
                "name": "Sam",
                "born": "2019-05-01",
                "trace_name": "SAM",
                "current_level": "adds",
                "next_steps": "2 digits",
                "log": [
                    {"day": "2026-01-10", "title": "Math", "file": "sam/m.pdf"},
                    {"day": "2026-01-12", "kind": "project", "title": "Puzzle"},
                ],
            }
        ],
        "ideas": [{"title": "Feeder", "machine": "cnc", "child": "sam"}],
    }
    r = import_data(app.db, app.files, data, base)
    assert r["children"] == 1 and r["entries"] == 2 and r["sheets"] == 1 and r["ideas"] == 1
    st = Store(app.db, app.files, r["family_id"])
    assert st.children()[0]["trace_name"] == "SAM"
    assert app.families.role(r["family_id"], "o@example.com") == "owner"
    assert {i["email"] for i in app.families.invites(r["family_id"])} == {"o2@example.com", "m@example.com"}
    with pytest.raises(ImportError_, match="twice"):
        import_data(app.db, app.files, data, base, family_id=r["family_id"])


def test_import_refuses_files_outside_folder(app, tmp_path):
    data = {
        "family": {"owners": ["o@example.com"]},
        "children": [
            {
                "name": "A",
                "born": "2020-01-01",
                "log": [{"day": "2026-01-01", "title": "x", "file": "../../etc/passwd"}],
            }
        ],
    }
    with pytest.raises(ImportError_):
        import_data(app.db, app.files, data, tmp_path)
