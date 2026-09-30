"""
agent/notepad_store.py — On-disk storage for the desktop-pet notepad.

The notepad is a single global markdown note at
``<DAGI_ROOT>/.dagi/notepad/notepad.md``. This module is Qt-free so the
``read_notepad`` tool can use it from any frontend (GUI, TUI, Telegram).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from agent import DAGI_ROOT

NOTEPAD_DIR = DAGI_ROOT / ".dagi" / "notepad"
_NOTE_NAME = "notepad.md"
_STATE_NAME = "state.json"


def notepad_path(root: Path = NOTEPAD_DIR) -> Path:
    return root / _NOTE_NAME


def read_text(root: Path = NOTEPAD_DIR) -> str:
    """Return the note's markdown, or "" when it does not exist yet."""
    try:
        with open(notepad_path(root), encoding="utf-8", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def write_text(text: str, root: Path = NOTEPAD_DIR) -> Path:
    """Atomically replace the note so readers never see a half-written file."""
    path = notepad_path(root)
    return atomic_write(path, text)


def atomic_write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    # newline="" keeps the editor's "\n" line endings byte-for-byte.
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return path


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def backup_conflict(text: str, root: Path = NOTEPAD_DIR, now: datetime | None = None) -> Path:
    """Save *text* (the on-disk version that lost a conflict) to a timestamped file."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    path = root / f"conflict-{stamp}.md"
    n = 1
    while path.exists():
        path = root / f"conflict-{stamp}-{n}.md"
        n += 1
    return atomic_write(path, text)


def load_state(root: Path = NOTEPAD_DIR) -> dict:
    """Return persisted UI state (currently only the notepad size); {} if absent or corrupt."""
    try:
        data = json.loads((root / _STATE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict, root: Path = NOTEPAD_DIR) -> None:
    atomic_write(root / _STATE_NAME, json.dumps(state, indent=2))
