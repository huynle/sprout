"""Google sign-in (OIDC authorization code + PKCE), server-side sessions and CSRF.

The ID token comes straight
from Google's token endpoint over TLS in exchange for our code, so (OIDC Core 3.1.3.7) TLS
stands in for the signature check; its claims are still checked. Who may sign in is decided by
families.py (membership or a pending invite), and only with email_verified.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

from sprout.db import Database

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
LOGIN_TTL = 600
MAX_PENDING_LOGINS = 200


class LoginError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _hash(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    sid_hash: str = field(repr=False)
    email: str
    family_id: int | None
    csrf: str = field(repr=False)


@dataclass(frozen=True)
class LoginFlow:
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    return_to: str

    @property
    def challenge(self) -> str:
        return base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()


class Sessions:
    def __init__(self, db: Database, idle: int, max_age: int, clock=time.time):
        self.db, self.idle, self.max_age, self.clock = db, idle, max_age, clock

    def create(self, email: str, family_id: int | None) -> tuple[str, Session]:
        now = self.clock()
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.db.run(
            "INSERT INTO web_sessions (id_hash, email, family_id, csrf_token, created_at, last_seen_at, "
            "expires_at) VALUES (?,?,?,?,?,?,?)",
            (_hash(sid), email, family_id, csrf, now, now, now + self.max_age),
        )
        return sid, Session(_hash(sid), email, family_id, csrf)

    def set_family(self, session: Session, family_id: int | None) -> None:
        self.db.run("UPDATE web_sessions SET family_id=? WHERE id_hash=?", (family_id, session.sid_hash))

    def get(self, sid: str | None) -> Session | None:
        if not sid or len(sid) > 128:
            return None
        row = self.db.one("SELECT * FROM web_sessions WHERE id_hash=?", (_hash(sid),))
        if not row:
            return None
        now = self.clock()
        if row["expires_at"] <= now or row["last_seen_at"] + self.idle <= now:
            self.db.run("DELETE FROM web_sessions WHERE id_hash=?", (_hash(sid),))
            return None
        if now - row["last_seen_at"] > 60:
            self.db.run("UPDATE web_sessions SET last_seen_at=? WHERE id_hash=?", (now, _hash(sid)))
        return Session(row["id_hash"], row["email"], row["family_id"], row["csrf_token"])

    def delete(self, sid: str | None) -> None:
        if sid and len(sid) <= 128:
            self.db.run("DELETE FROM web_sessions WHERE id_hash=?", (_hash(sid),))

    def revoke_email(self, email: str) -> None:
        self.db.run("DELETE FROM web_sessions WHERE email=?", (email,))

    def start_login(self, return_to: str) -> LoginFlow | None:
        now = self.clock()
        self.db.run("DELETE FROM login_flows WHERE expires_at<=?", (now,))
        (n,) = self.db.one("SELECT COUNT(*) FROM login_flows")
        if n >= MAX_PENDING_LOGINS:
            return None
        f = LoginFlow(
            secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48), return_to
        )
        self.db.run(
            "INSERT INTO login_flows VALUES (?,?,?,?,?)",
            (_hash(f.state), f.nonce, f.verifier, return_to, now + LOGIN_TTL),
        )
        return f

    def take_login(self, state: str | None) -> LoginFlow | None:
        if not state or len(state) > 128:
            return None
        row = self.db.one("SELECT * FROM login_flows WHERE state_hash=?", (_hash(state),))
        self.db.run("DELETE FROM login_flows WHERE state_hash=?", (_hash(state),))
        if not row or row["expires_at"] <= self.clock():
            return None
        return LoginFlow(state, row["nonce"], row["code_verifier"], row["return_to"])


def safe_return_to(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value or len(value) > 300:
        return "/"
    return value


def authorization_url(client_id: str, redirect_uri: str, flow: LoginFlow) -> str:
    return (
        AUTHORIZE_URL
        + "?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": "openid email",
                "state": flow.state,
                "nonce": flow.nonce,
                "code_challenge": flow.challenge,
                "code_challenge_method": "S256",
                "prompt": "select_account",
            }
        )
    )


async def exchange_code(
    http: httpx.AsyncClient, client_id: str, secret: str, redirect_uri: str, code: str, verifier: str
) -> str:
    try:
        r = await http.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": secret,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
    except httpx.HTTPError:
        raise LoginError(502, "Could not reach Google. Try signing in again.") from None
    if r.status_code != 200:
        log.warning("google token endpoint HTTP %d", r.status_code)
        raise LoginError(400, "Google did not accept the sign-in. Try again.")
    try:
        tok = r.json().get("id_token")
    except ValueError:
        tok = None
    if not isinstance(tok, str):
        raise LoginError(400, "Google returned an unexpected response. Try again.")
    return tok


def validate_id_token(id_token: str, client_id: str, nonce: str, now: float) -> tuple[str, bool]:
    """Return (email, email_verified) or raise LoginError(400)."""
    bad = LoginError(400, "The sign-in response was invalid. Try signing in again.")
    try:
        parts = id_token.split(".")
        if len(id_token) > 16384 or len(parts) != 3:
            raise ValueError
        claims: Any = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        if not isinstance(claims, dict):
            raise ValueError
    except (ValueError, binascii.Error):
        raise bad from None
    aud = claims.get("aud")
    if (
        claims.get("iss") not in ISSUERS
        or client_id not in (aud if isinstance(aud, list) else [aud])
        or ("azp" in claims and claims["azp"] != client_id)
        or not isinstance(claims.get("exp"), int | float)
        or claims["exp"] <= now
        or not nonce
        or claims.get("nonce") != nonce
        or not isinstance(claims.get("email"), str)
        or not claims["email"]
    ):
        raise bad
    ev = claims.get("email_verified")
    return claims["email"].lower(), ev is True or (isinstance(ev, str) and ev.lower() == "true")
