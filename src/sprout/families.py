"""Families, members and invites. Membership is the only way into a family's data.

Sign-in rule: a verified Google email may sign in if it is a member of a family, has a pending
invite (accepted automatically, since Google verified the address), or is an instance admin.
"""

from __future__ import annotations

import re
import time

from sprout.db import Database

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$")


class FamilyError(ValueError):
    pass


def norm_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not EMAIL.match(e):
        raise FamilyError("That doesn't look like an email address.")
    return e


class Families:
    def __init__(self, db: Database):
        self.db = db

    def create(self, name: str, owner_email: str, actor: str) -> int:
        name = name.strip()[:80]
        if not name:
            raise FamilyError("Give the family a name.")
        fid = self.db.run("INSERT INTO families (name, created_at) VALUES (?,?)", (name, time.time()))
        self.db.run(
            "INSERT INTO members VALUES (?,?,?,?)", (fid, norm_email(owner_email), "owner", time.time())
        )
        self.db.audit(fid, actor, "family.create", owner=owner_email)
        return fid

    def get(self, fid: int) -> dict | None:
        r = self.db.one("SELECT * FROM families WHERE id=?", (fid,))
        return dict(r) if r else None

    def rename(self, fid: int, name: str, actor: str) -> None:
        if not name.strip():
            raise FamilyError("Give the family a name.")
        self.db.run("UPDATE families SET name=? WHERE id=?", (name.strip()[:80], fid))
        self.db.audit(fid, actor, "family.rename")

    def all(self) -> list[dict]:
        return [
            dict(r)
            for r in self.db.q(
                "SELECT f.*, (SELECT COUNT(*) FROM members m WHERE m.family_id=f.id) AS members, "
                "(SELECT COUNT(*) FROM children c WHERE c.family_id=f.id) AS children FROM families f ORDER BY id"
            )
        ]

    def of(self, email: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.q(
                "SELECT f.id, f.name, m.role FROM members m JOIN families f ON f.id=m.family_id WHERE m.email=? "
                "ORDER BY f.id",
                (email.lower(),),
            )
        ]

    def role(self, fid: int | None, email: str) -> str | None:
        if fid is None:
            return None
        r = self.db.one("SELECT role FROM members WHERE family_id=? AND email=?", (fid, email.lower()))
        return r["role"] if r else None

    def members(self, fid: int) -> list[dict]:
        return [
            dict(r)
            for r in self.db.q(
                "SELECT email, role, created_at FROM members WHERE family_id=? ORDER BY role DESC, email",
                (fid,),
            )
        ]

    def invites(self, fid: int) -> list[dict]:
        return [
            dict(r)
            for r in self.db.q(
                "SELECT * FROM invites WHERE family_id=? AND accepted_at IS NULL ORDER BY id DESC", (fid,)
            )
        ]

    def invite(self, fid: int, email: str, role: str, actor: str) -> None:
        if role not in ("owner", "member"):
            raise FamilyError("Unknown role.")
        e = norm_email(email)
        if self.role(fid, e):
            raise FamilyError(f"{e} is already in this family.")
        self.db.run(
            "INSERT INTO invites (family_id, email, role, created_by, created_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(family_id, email) DO UPDATE SET role=excluded.role, accepted_at=NULL",
            (fid, e, role, actor, time.time()),
        )
        self.db.audit(fid, actor, "invite.create", email=e, role=role)

    def cancel_invite(self, fid: int, email: str, actor: str) -> None:
        self.db.run(
            "DELETE FROM invites WHERE family_id=? AND email=? AND accepted_at IS NULL", (fid, email.lower())
        )
        self.db.audit(fid, actor, "invite.cancel", email=email)

    def remove_member(self, fid: int, email: str, actor: str) -> None:
        owners = [m for m in self.members(fid) if m["role"] == "owner"]
        if self.role(fid, email) == "owner" and len(owners) == 1:
            raise FamilyError("A family needs at least one owner.")
        self.db.run("DELETE FROM members WHERE family_id=? AND email=?", (fid, email.lower()))
        self.db.run(
            "UPDATE web_sessions SET family_id=NULL WHERE email=? AND family_id=?", (email.lower(), fid)
        )
        self.db.audit(fid, actor, "member.remove", email=email)

    def accept_pending(self, email: str) -> list[int]:
        """Turn every pending invite for this (Google-verified) email into membership."""
        e = email.lower()
        joined = []
        for r in self.db.q("SELECT * FROM invites WHERE email=? AND accepted_at IS NULL", (e,)):
            self.db.run(
                "INSERT OR IGNORE INTO members VALUES (?,?,?,?)", (r["family_id"], e, r["role"], time.time())
            )
            self.db.run("UPDATE invites SET accepted_at=? WHERE id=?", (time.time(), r["id"]))
            self.db.audit(r["family_id"], e, "invite.accept")
            joined.append(r["family_id"])
        return joined
