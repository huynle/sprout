"""Import a family's existing history from a JSON file (format in docs/import.md).

Files referenced by the JSON (PDFs) are resolved relative to the JSON file. The import is
all-or-nothing per run only in the sense that it refuses to touch a family that already has
children, so running it twice doesn't duplicate anything.
"""

from __future__ import annotations

import json
from pathlib import Path

from sprout.config import Settings
from sprout.db import Database
from sprout.families import Families
from sprout.store import Files, Store


class ImportError_(ValueError):
    pass


def import_data(
    db: Database, files: Files, data: dict, base: Path, family_id: int | None = None, actor: str = "import"
) -> dict:
    fams = Families(db)
    fam = data.get("family") or {}
    if family_id is None:
        owners = fam.get("owners") or []
        if not owners:
            raise ImportError_("family.owners must list at least one email")
        family_id = fams.create(fam.get("name") or "Family", owners[0], actor)
        for e in owners[1:]:
            fams.invite(family_id, e, "owner", actor)
        for e in fam.get("members") or []:
            fams.invite(family_id, e, "member", actor)
    elif not fams.get(family_id):
        raise ImportError_(f"no family {family_id}")
    st = Store(db, files, family_id)
    if st.children():
        raise ImportError_("that family already has children; refusing to import twice")
    counts = {"family_id": family_id, "children": 0, "entries": 0, "sheets": 0, "ideas": 0}
    ids: dict[str, int] = {}
    for c in data.get("children") or []:
        cid = st.add_child(c["name"], c["born"], actor, c.get("trace_name", ""))
        ids[c.get("key") or c["name"]] = cid
        st.update_child(
            cid, actor, current_level=c.get("current_level", ""), next_steps=c.get("next_steps", "")
        )
        counts["children"] += 1
        for e in c.get("log") or []:
            sheet_id = None
            if e.get("file"):
                p = (base / e["file"]).resolve()
                if base.resolve() not in p.parents or not p.exists():
                    raise ImportError_(f"file not found next to the import file: {e['file']}")
                sheet_id = st.add_sheet(
                    cid,
                    "import",
                    e.get("title") or p.name,
                    {"note": e.get("detail", "")},
                    p.read_bytes(),
                    actor,
                    source="import",
                )
                counts["sheets"] += 1
            st.add_entry(
                cid,
                e.get("kind", "sheet"),
                e["title"],
                actor,
                detail=e.get("detail", ""),
                rating=e.get("rating"),
                sheet_id=sheet_id,
                day=e["day"],
            )
            counts["entries"] += 1
    for i in data.get("ideas") or []:
        child = ids.get(i["child"]) if i.get("child") else None
        st.add_idea(
            i["title"],
            i.get("detail", ""),
            i.get("machine", "other"),
            child,
            actor,
            status=i.get("status", "idea"),
            link=i.get("link", ""),
        )
        counts["ideas"] += 1
    return counts


def import_file(settings: Settings, path: Path, family_id: int | None = None) -> dict:
    db = Database(settings.data_dir / "sprout.db")
    return import_data(
        db, Files(settings.data_dir / "files"), json.loads(path.read_text()), path.parent, family_id
    )
