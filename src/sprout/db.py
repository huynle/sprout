"""SQLite storage: one file in DATA_DIR, migrations applied in order at startup.

Every family-owned row carries family_id. Store (store.py) adds family_id to every query, so a
member can only ever see their own family's data; tests/test_isolation.py checks that.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

MIGRATIONS = [
    """
    CREATE TABLE families (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE members (
        family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
        email TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('owner','member')),
        created_at REAL NOT NULL,
        PRIMARY KEY (family_id, email)
    );
    CREATE INDEX members_email ON members(email);
    CREATE TABLE invites (
        id INTEGER PRIMARY KEY,
        family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
        email TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('owner','member')),
        created_by TEXT NOT NULL,
        created_at REAL NOT NULL,
        accepted_at REAL,
        UNIQUE (family_id, email)
    );
    CREATE TABLE children (
        id INTEGER PRIMARY KEY,
        family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        born TEXT NOT NULL,                  -- YYYY-MM-DD
        sort INTEGER NOT NULL DEFAULT 0,
        current_level TEXT NOT NULL DEFAULT '',
        next_steps TEXT NOT NULL DEFAULT '',
        trace_name TEXT NOT NULL DEFAULT ''  -- how the child writes their name, e.g. SAM
    );
    CREATE TABLE sheets (
        id INTEGER PRIMARY KEY,
        family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
        child_id INTEGER REFERENCES children(id) ON DELETE SET NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        params TEXT NOT NULL DEFAULT '{}',
        file TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('draft','final')),
        source TEXT NOT NULL DEFAULT 'form' CHECK (source IN ('form','ai','agent','import')),
        created_by TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE entries (
        id INTEGER PRIMARY KEY,
        family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
        child_id INTEGER NOT NULL REFERENCES children(id) ON DELETE CASCADE,
        day TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('sheet','project','note','feedback')),
        title TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        rating TEXT CHECK (rating IN ('too_easy','just_right','too_hard','loved_it') OR rating IS NULL),
        sheet_id INTEGER REFERENCES sheets(id) ON DELETE SET NULL,
        created_by TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE coloring (
        id INTEGER PRIMARY KEY,
        family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '',
        file TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE requests (
        id INTEGER PRIMARY KEY,
        family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
        child_id INTEGER REFERENCES children(id) ON DELETE SET NULL,
        text TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('working','done','failed','needs_human')),
        plan TEXT NOT NULL DEFAULT '{}',
        sheet_id INTEGER REFERENCES sheets(id) ON DELETE SET NULL,
        message TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE ideas (
        id INTEGER PRIMARY KEY,
        family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
        child_id INTEGER REFERENCES children(id) ON DELETE SET NULL,
        title TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        machine TEXT NOT NULL DEFAULT 'other' CHECK (machine IN ('cnc','laser','print','other')),
        status TEXT NOT NULL DEFAULT 'idea' CHECK (status IN ('idea','planned','built','dropped')),
        link TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE audit (
        id INTEGER PRIMARY KEY,
        family_id INTEGER,
        at REAL NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE web_sessions (
        id_hash TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        family_id INTEGER REFERENCES families(id) ON DELETE SET NULL,
        csrf_token TEXT NOT NULL,
        created_at REAL NOT NULL,
        last_seen_at REAL NOT NULL,
        expires_at REAL NOT NULL
    );
    CREATE TABLE login_flows (
        state_hash TEXT PRIMARY KEY,
        nonce TEXT NOT NULL,
        code_verifier TEXT NOT NULL,
        return_to TEXT NOT NULL,
        expires_at REAL NOT NULL
    );
    """,
]


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            (version,) = self.conn.execute("PRAGMA user_version").fetchone()
            for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                self.conn.executescript("BEGIN;" + sql + f"PRAGMA user_version={i};COMMIT;")

    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, args).fetchone()

    def run(self, sql: str, args: tuple = ()) -> int:
        """Execute a write; return lastrowid for INSERT, else rowcount."""
        with self._lock:
            cur = self.conn.execute(sql, args)
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount

    def audit(self, family_id: int | None, actor: str, action: str, **detail: Any) -> None:
        self.run(
            "INSERT INTO audit (family_id, at, actor, action, detail) VALUES (?,?,?,?,?)",
            (family_id, time.time(), actor, action, json.dumps(detail, default=str)),
        )
