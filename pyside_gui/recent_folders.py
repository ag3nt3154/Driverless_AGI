"""Most-recently-opened project folders, persisted as JSON for the header folder menu."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from agent import DAGI_ROOT

MAX_RECENT = 5
_STORE = DAGI_ROOT / ".dagi" / "recent_folders.json"

log = logging.getLogger(__name__)


def load(store: Path | None = None) -> list[Path]:
    """Return recent folders, newest first. Missing folders are kept (the menu greys them)."""
    store = store or _STORE
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        log.warning("Ignoring unreadable recent-folders file %s: %s", store, exc)
        return []
    if not isinstance(data, list):
        log.warning("Ignoring malformed recent-folders file %s", store)
        return []
    return [Path(p) for p in data if isinstance(p, str)][:MAX_RECENT]


def push(path: Path, store: Path | None = None) -> list[Path]:
    """Move *path* to the front, drop duplicates (case-insensitive on Windows), cap, save."""
    store = store or _STORE
    key = os.path.normcase(str(path))
    rest = [p for p in load(store) if os.path.normcase(str(p)) != key]
    folders = [path, *rest][:MAX_RECENT]
    _save(folders, store)
    return folders


def clear(store: Path | None = None) -> None:
    _save([], store or _STORE)


def _save(folders: list[Path], store: Path) -> None:
    # Recents are a convenience; a failed write must not break the folder switch.
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps([str(p) for p in folders], indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("Could not save recent folders to %s: %s", store, exc)
