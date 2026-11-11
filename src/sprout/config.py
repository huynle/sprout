"""Settings from the environment (documented in README.md, checked by tests/test_readme.py)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


def _emails(raw: str | None) -> tuple[str, ...]:
    return tuple(sorted({e.strip().lower() for e in (raw or "").replace(";", ",").split(",") if e.strip()}))


@dataclass(frozen=True)
class Settings:
    public_base_url: str = "http://localhost:8000"
    data_dir: Path = Path("data")
    admins: tuple[str, ...] = ()
    google_client_id: str = ""
    google_client_secret: str = field(default="", repr=False)
    dev_login_email: str = ""
    printer_url: str = ""
    printer_token: str = field(default="", repr=False)
    printer_id: str = ""
    llm_url: str = ""
    llm_key: str = field(default="", repr=False)
    llm_model: str = ""
    image_model: str = ""
    session_idle_seconds: int = 14 * 24 * 3600
    session_max_seconds: int = 90 * 24 * 3600
    max_upload_bytes: int = 20 * 1024 * 1024

    @property
    def secure_cookies(self) -> bool:
        return self.public_base_url.startswith("https://")

    @property
    def is_local(self) -> bool:
        return urlparse(self.public_base_url).hostname in {"localhost", "127.0.0.1"}

    @property
    def origin(self) -> str:
        u = urlparse(self.public_base_url)
        return f"{u.scheme}://{u.netloc}"

    def is_admin(self, email: str | None) -> bool:
        return (email or "").lower() in self.admins

    def check(self) -> None:
        if not self.admins:
            raise RuntimeError("SPROUT_ADMINS must list at least one email (instance administrators)")
        if self.dev_login_email and not self.is_local:
            raise RuntimeError("DEV_LOGIN_EMAIL is only allowed when PUBLIC_BASE_URL is localhost")
        if not self.dev_login_email and not (self.google_client_id and self.google_client_secret):
            raise RuntimeError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required (or DEV_LOGIN_EMAIL locally)"
            )


ENV = {
    "PUBLIC_BASE_URL": "public_base_url",
    "DATA_DIR": "data_dir",
    "SPROUT_ADMINS": "admins",
    "GOOGLE_CLIENT_ID": "google_client_id",
    "GOOGLE_CLIENT_SECRET": "google_client_secret",
    "DEV_LOGIN_EMAIL": "dev_login_email",
    "PRINTER_URL": "printer_url",
    "PRINTER_TOKEN": "printer_token",
    "PRINTER_ID": "printer_id",
    "LLM_URL": "llm_url",
    "LLM_KEY": "llm_key",
    "LLM_MODEL": "llm_model",
    "IMAGE_MODEL": "image_model",
}


def from_env(env: dict[str, str] | None = None) -> Settings:
    e = os.environ if env is None else env
    kw = {}
    for var, attr in ENV.items():
        if var not in e:
            continue
        v = e[var]
        if attr == "admins":
            kw[attr] = _emails(v)
        elif attr == "data_dir":
            kw[attr] = Path(v)
        elif attr in ("public_base_url", "printer_url", "llm_url"):
            kw[attr] = v.rstrip("/")
        elif attr == "dev_login_email":
            kw[attr] = v.strip().lower()
        else:
            kw[attr] = v
    return Settings(**kw)
