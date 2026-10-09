"""Board address settings from config.yaml and the shared bearer-token file."""
from __future__ import annotations

import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from agent import DAGI_ROOT

from .lifecycle import DEFAULT_URL

STATE_ROOT = DAGI_ROOT / ".dagi" / "board"
TOKEN_PATH = STATE_ROOT / "token"
DEFAULT_BIND = "0.0.0.0"


@dataclass(frozen=True)
class BoardSettings:
    url: str = DEFAULT_URL
    bind: str = DEFAULT_BIND

    @property
    def port(self) -> int:
        return urlsplit(self.url).port or 80


def board_settings(services) -> BoardSettings:
    """Read ``services.message_board``: a URL string or a ``{url, bind}`` mapping."""
    value = (services or {}).get("message_board") if isinstance(services, dict) else None
    if isinstance(value, str) and value.strip():
        return BoardSettings(url=value.strip())
    if isinstance(value, dict):
        url = value.get("url")
        bind = value.get("bind")
        return BoardSettings(
            url=url.strip() if isinstance(url, str) and url.strip() else DEFAULT_URL,
            bind=bind.strip() if isinstance(bind, str) and bind.strip() else DEFAULT_BIND,
        )
    return BoardSettings()


def load_settings() -> BoardSettings:
    """Settings from {DAGI_ROOT}/.dagi/config.yaml; defaults when it is absent."""
    from agent.config_loader import load_raw_config

    return board_settings(load_raw_config().get("services"))


def read_token(path: Path = TOKEN_PATH) -> str | None:
    """Return the stored token, or None when the file is absent, empty or a link."""
    path = Path(path)
    if path.is_symlink():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, NotADirectoryError):
        return None
    return value or None


def resolve_token(explicit: str | None = None, path: Path = TOKEN_PATH) -> str | None:
    """Token precedence: explicit value, then env DAGI_BOARD_TOKEN, then the token file."""
    return explicit or os.environ.get("DAGI_BOARD_TOKEN") or read_token(path)


def ensure_token(path: Path = TOKEN_PATH) -> str:
    """Return the resolved token, generating and storing one when none exists."""
    existing = resolve_token(None, path)
    if existing:
        return existing
    path = Path(path)
    if path.is_symlink():
        raise OSError(f"board token path must not be a link: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(value + "\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return value
