"""Board address settings from config.yaml and the bearer token from .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from agent import DAGI_ROOT

from .lifecycle import DEFAULT_URL

STATE_ROOT = DAGI_ROOT / ".dagi" / "board"
ENV_PATH = DAGI_ROOT / ".env"
DEFAULT_TOKEN = "dagi"
CONFIG_PATH = DAGI_ROOT / ".dagi" / "config.yaml"
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


def load_settings(path: Path = CONFIG_PATH) -> BoardSettings:
    """Settings from {DAGI_ROOT}/.dagi/config.yaml; defaults when it is absent.

    Reads the YAML directly: agent.config_loader imports the agent loop and openai, which
    adds seconds to every board start.
    """
    import yaml

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raw = {}
    return board_settings(raw.get("services") if isinstance(raw, dict) else None)


def _dotenv_token(path: Path) -> str | None:
    """``DAGI_BOARD_TOKEN`` from a .env file, read without touching ``os.environ``."""
    from dotenv import dotenv_values

    try:
        return dotenv_values(path).get("DAGI_BOARD_TOKEN")
    except OSError:
        return None


def resolve_token(explicit: str | None = None, env_path: Path = ENV_PATH) -> str:
    """Token precedence: explicit value, env DAGI_BOARD_TOKEN, .env, then ``"dagi"``.

    Blank values fall through, so a board always has a token.
    """
    for value in (explicit, os.environ.get("DAGI_BOARD_TOKEN"), _dotenv_token(env_path)):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return DEFAULT_TOKEN
