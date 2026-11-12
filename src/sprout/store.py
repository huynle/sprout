"""Family-scoped data access. A Store is bound to one family; every query filters on family_id and
every cross-reference (child, sheet, idea) is checked to belong to the same family."""

from __future__ import annotations

import json
import secrets
import time
from datetime import date
from pathlib import Path
from typing import Any

from sprout.children import age_on, next_birthday
from sprout.db import Database

RATINGS = {"too_easy": "Too easy", "just_right": "Just right", "too_hard": "Too hard", "loved_it": "Loved it"}
MACHINES = {"cnc": "CNC router", "laser": "Laser cutter", "print": "Printer", "other": "Other"}
IDEA_STATUS = {"idea": "Idea", "planned": "Planned", "built": "Built", "dropped": "Dropped"}


class NotFound(LookupError):
    pass


class QuotaExceeded(ValueError):
    pass


class Files:
    """Opaque file names under one directory; families never share a name space."""

    def __init__(self, root: Path, quota_bytes: int | None = None):
        self.root = root
        self.quota = quota_bytes
        root.mkdir(parents=True, exist_ok=True)

    def used(self, family_id: int) -> int:
        folder = self.root / str(family_id)
        return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) if folder.exists() else 0

    def save(self, family_id: int, data: bytes, ext: str) -> str:
        if self.quota is not None and self.used(family_id) + len(data) > self.quota:
            raise QuotaExceeded(
                "Your family's storage is full. Delete the family's old files or ask the operator."
            )
        name = f"{family_id}/{time.strftime('%Y%m')}/{secrets.token_hex(12)}.{ext}"
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return name

    def path(self, family_id: int, name: str) -> Path:
        p = (self.root / name).resolve()
        if not name.startswith(f"{family_id}/") or (self.root.resolve() / str(family_id)) not in p.parents:
            raise NotFound(name)
        return p


class Store:
    def __init__(self, db: Database, files: Files, family_id: int, today=date.today):
        self.db, self.files, self.fid, self.today = db, files, family_id, today

    def audit(self, actor: str, action: str, **detail: Any) -> None:
        self.db.audit(self.fid, actor, action, **detail)

    def file(self, name: str) -> Path:
        return self.files.path(self.fid, name)

    # -- children ----------------------------------------------------------------
    def children(self) -> list[dict]:
        return [
            self._child(r)
            for r in self.db.q("SELECT * FROM children WHERE family_id=? ORDER BY sort, name", (self.fid,))
        ]

    def child(self, cid: int | str | None) -> dict:
        try:
            cid = int(cid)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise NotFound("child") from None
        r = self.db.one("SELECT * FROM children WHERE id=? AND family_id=?", (cid, self.fid))
        if not r:
            raise NotFound("child")
        return self._child(r)

    def _child(self, r) -> dict:
        born, today = date.fromisoformat(r["born"]), self.today()
        bday, days = next_birthday(born, today)
        last = self.db.one(
            "SELECT title, day FROM entries WHERE family_id=? AND child_id=? "
            "AND kind IN ('sheet','project') ORDER BY day DESC, id DESC LIMIT 1",
            (self.fid, r["id"]),
        )
        age = age_on(born, today)
        return {
            **dict(r),
            "age": str(age),
            "age_years": age.years,
            "next_birthday": bday.isoformat(),
            "birthday_in": days,
            "turning": age_on(born, bday).years,
            "last": dict(last) if last else None,
        }

    def add_child(self, name: str, born: str, actor: str, trace_name: str = "") -> int:
        name = name.strip()[:40]
        if not name:
            raise ValueError("Give the child's first name.")
        try:
            b = date.fromisoformat(born)
        except ValueError:
            raise ValueError("Birth date must look like 2020-04-24.") from None
        if not date(1990, 1, 1) <= b <= self.today():
            raise ValueError("That birth date doesn't look right.")
        (n,) = self.db.one("SELECT COUNT(*) FROM children WHERE family_id=?", (self.fid,))
        cid = self.db.run(
            "INSERT INTO children (family_id, name, born, sort, trace_name) VALUES (?,?,?,?,?)",
            (self.fid, name, b.isoformat(), n, (trace_name or name).strip()[:20]),
        )
        self.audit(actor, "child.add", id=cid)
        return cid

    def update_child(self, cid: int, actor: str, **fields: str) -> None:
        c = self.child(cid)
        allowed = {"name", "born", "current_level", "next_steps", "trace_name"}
        vals = {k: str(v).strip()[:4000] for k, v in fields.items() if k in allowed}
        if "born" in vals:
            date.fromisoformat(vals["born"])
        if "name" in vals and not vals["name"]:
            raise ValueError("Name can't be empty.")
        if vals:
            sets = ", ".join(f"{k}=?" for k in vals)
            self.db.run(
                f"UPDATE children SET {sets} WHERE id=? AND family_id=?", (*vals.values(), c["id"], self.fid)
            )
            self.audit(actor, "child.update", id=c["id"], fields=sorted(vals))

    # -- log ---------------------------------------------------------------------
    def entries(self, cid: int, limit: int = 100) -> list[dict]:
        return [
            dict(r)
            for r in self.db.q(
                "SELECT * FROM entries WHERE family_id=? AND child_id=? ORDER BY day DESC, id DESC LIMIT ?",
                (self.fid, int(cid), limit),
            )
        ]

    def add_entry(
        self,
        cid: int,
        kind: str,
        title: str,
        actor: str,
        detail: str = "",
        rating: str | None = None,
        sheet_id: int | None = None,
        day: str | None = None,
    ) -> int:
        c = self.child(cid)
        if rating and rating not in RATINGS:
            raise ValueError("bad rating")
        if sheet_id is not None:
            self.sheet(sheet_id)
        eid = self.db.run(
            "INSERT INTO entries (family_id, child_id, day, kind, title, detail, rating, sheet_id, created_by, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                self.fid,
                c["id"],
                day or self.today().isoformat(),
                kind,
                title.strip()[:300],
                detail.strip()[:4000],
                rating,
                sheet_id,
                actor,
                time.time(),
            ),
        )
        self.audit(actor, "entry.add", child=c["id"], kind=kind, id=eid)
        return eid

    # -- sheets ------------------------------------------------------------------
    def add_sheet(
        self,
        cid: int | None,
        kind: str,
        title: str,
        params: dict,
        pdf: bytes,
        actor: str,
        status: str = "final",
        source: str = "form",
    ) -> int:
        if cid is not None:
            cid = self.child(cid)["id"]
        name = self.files.save(self.fid, pdf, "pdf")
        sid = self.db.run(
            "INSERT INTO sheets (family_id, child_id, kind, title, params, file, status, source, created_by, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (self.fid, cid, kind, title[:200], json.dumps(params), name, status, source, actor, time.time()),
        )
        self.audit(actor, "sheet.add", id=sid, kind=kind, child=cid, source=source)
        return sid

    def sheets_since(self, kinds: tuple[str, ...], since: float) -> int:
        """How many sheets of these kinds this family made since ``since`` (daily caps)."""
        if not kinds:
            return 0
        marks = ",".join("?" * len(kinds))
        (n,) = self.db.one(
            f"SELECT COUNT(*) FROM sheets WHERE family_id=? AND created_at>? AND kind IN ({marks})",
            (self.fid, since, *kinds),
        )
        return n

    def sheet(self, sid: int | str) -> dict:
        try:
            r = self.db.one("SELECT * FROM sheets WHERE id=? AND family_id=?", (int(sid), self.fid))
        except (TypeError, ValueError):
            r = None
        if not r:
            raise NotFound("sheet")
        return {**dict(r), "params": json.loads(r["params"])}

    def sheets(self, cid: int | None = None, limit: int = 50) -> list[dict]:
        if cid is not None:
            rows = self.db.q(
                "SELECT * FROM sheets WHERE family_id=? AND child_id=? ORDER BY id DESC LIMIT ?",
                (self.fid, int(cid), limit),
            )
        else:
            rows = self.db.q(
                "SELECT * FROM sheets WHERE family_id=? ORDER BY id DESC LIMIT ?", (self.fid, limit)
            )
        return [dict(r) for r in rows]

    def keep_sheet(self, sid: int, actor: str, child_id: int | None = None) -> None:
        """Accept a draft: it becomes final and is logged for its child."""
        s = self.sheet(sid)
        if child_id is not None and not s["child_id"]:
            s["child_id"] = self.child(child_id)["id"]
            self.db.run(
                "UPDATE sheets SET child_id=? WHERE id=? AND family_id=?", (s["child_id"], s["id"], self.fid)
            )
        if s["status"] == "draft":
            self.db.run("UPDATE sheets SET status='final' WHERE id=? AND family_id=?", (s["id"], self.fid))
            if s["child_id"]:
                self.add_entry(s["child_id"], "sheet", s["title"], actor, sheet_id=s["id"])
            self.audit(actor, "sheet.keep", id=s["id"])

    # -- coloring ----------------------------------------------------------------
    def coloring(self, tag: str | None = None) -> list[dict]:
        items = [
            dict(r)
            for r in self.db.q("SELECT * FROM coloring WHERE family_id=? ORDER BY id DESC", (self.fid,))
        ]
        if tag:
            items = [i for i in items if tag.lower() in i["tags"].split(",")]
        return items

    def coloring_page(self, pid: int | str) -> dict:
        try:
            r = self.db.one("SELECT * FROM coloring WHERE id=? AND family_id=?", (int(pid), self.fid))
        except (TypeError, ValueError):
            r = None
        if not r:
            raise NotFound("coloring page")
        return dict(r)

    def add_coloring(self, title: str, tags: str, pdf: bytes, actor: str, source_url: str = "") -> int:
        name = self.files.save(self.fid, pdf, "pdf")
        tags = ",".join(t.strip().lower() for t in tags.split(",") if t.strip())[:200]
        pid = self.db.run(
            "INSERT INTO coloring (family_id, title, tags, source_url, file, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                self.fid,
                (title.strip() or "Coloring page")[:200],
                tags,
                source_url[:500],
                name,
                actor,
                time.time(),
            ),
        )
        self.audit(actor, "coloring.add", id=pid)
        return pid

    def tags(self) -> list[str]:
        return sorted({t for i in self.coloring() for t in i["tags"].split(",") if t})

    # -- requests ----------------------------------------------------------------
    def add_request(self, cid: int | None, text: str, actor: str) -> int:
        if cid is not None:
            cid = self.child(cid)["id"]
        rid = self.db.run(
            "INSERT INTO requests (family_id, child_id, text, status, created_by, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (self.fid, cid, text.strip()[:1000], "working", actor, time.time()),
        )
        self.audit(actor, "request.add", id=rid)
        return rid

    def finish_request(
        self, rid: int, status: str, plan: dict | None = None, sheet_id: int | None = None, message: str = ""
    ) -> None:
        self.db.run(
            "UPDATE requests SET status=?, plan=?, sheet_id=?, message=? WHERE id=? AND family_id=?",
            (status, json.dumps(plan or {}), sheet_id, message[:1000], rid, self.fid),
        )
        self.audit("assistant", "request." + status, id=rid)

    def requests(self, limit: int = 30) -> list[dict]:
        return [
            dict(r)
            for r in self.db.q(
                "SELECT * FROM requests WHERE family_id=? ORDER BY id DESC LIMIT ?", (self.fid, limit)
            )
        ]

    # -- ideas -------------------------------------------------------------------
    def ideas(self) -> list[dict]:
        return [
            dict(r)
            for r in self.db.q(
                "SELECT * FROM ideas WHERE family_id=? ORDER BY CASE status WHEN 'planned' THEN 0 WHEN 'idea' THEN 1 "
                "WHEN 'built' THEN 2 ELSE 3 END, id DESC",
                (self.fid,),
            )
        ]

    def add_idea(
        self,
        title: str,
        detail: str,
        machine: str,
        child_id: int | None,
        actor: str,
        status: str = "idea",
        link: str = "",
    ) -> int:
        if not title.strip():
            raise ValueError("Give the idea a short title.")
        if machine not in MACHINES or status not in IDEA_STATUS:
            raise ValueError("Unknown machine or status.")
        if child_id is not None:
            child_id = self.child(child_id)["id"]
        iid = self.db.run(
            "INSERT INTO ideas (family_id, child_id, title, detail, machine, status, link, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                self.fid,
                child_id,
                title.strip()[:200],
                detail.strip()[:4000],
                machine,
                status,
                link[:500],
                actor,
                time.time(),
            ),
        )
        self.audit(actor, "idea.add", id=iid)
        return iid

    def set_idea_status(self, iid: int, status: str, actor: str) -> None:
        if status not in IDEA_STATUS:
            raise ValueError("Unknown status.")
        if not self.db.run(
            "UPDATE ideas SET status=? WHERE id=? AND family_id=?", (status, int(iid), self.fid)
        ):
            raise NotFound("idea")
        self.audit(actor, "idea.status", id=iid, status=status)

    def stats(self) -> dict[str, int]:
        one = lambda sql: self.db.one(sql, (self.fid,))[0]
        return {
            "sheets": one("SELECT COUNT(*) FROM sheets WHERE family_id=? AND status='final'"),
            "coloring": one("SELECT COUNT(*) FROM coloring WHERE family_id=?"),
            "ideas": one("SELECT COUNT(*) FROM ideas WHERE family_id=? AND status IN ('idea','planned')"),
        }
