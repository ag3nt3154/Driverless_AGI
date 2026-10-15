"""Persistent board identity for this GUI: the main agent's handle and member key files."""
from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path

from agent.board_client import BoardError, new_key
from services.message_board.runtime_records import RecordError, protect


_KEY_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")


def _valid_handle(value: str, slug: str) -> bool:
    head, separator, tail = value.partition("_")
    return head == slug and separator == "_" and len(tail) == 8 and all(
        char in "0123456789abcdef" for char in tail
    )


def _load_or_create(path: Path, valid, make, *, secret: bool = False) -> str:
    """Return the valid value persisted at ``path``, replacing it with ``make()`` otherwise.

    A ``secret`` file is restricted to this user before it takes its final name.
    """
    path = Path(path)
    if path.is_symlink():
        raise BoardError("IDENTITY_ERROR", "board identity path must not be a link")
    try:
        value = path.read_text(encoding="utf-8").strip()
        if valid(value):
            return value
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    value = make()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            if secret:
                protect(temporary)
            stream.write(value + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except (OSError, RecordError) as error:
        raise BoardError("IDENTITY_ERROR", "cannot persist the board user identity") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return value


def load_or_create_handle(path: Path, slug: str) -> str:
    """Return the persisted ``<slug>_<uuid8>`` at ``path``, creating it when absent or invalid."""
    return _load_or_create(path, lambda value: _valid_handle(value, slug),
                           lambda: f"{slug}_{uuid.uuid4().hex[:8]}")


def load_or_create_key(path: Path) -> str:
    """Return the persisted member key at ``path``, creating a private one when absent."""
    return _load_or_create(path, lambda value: bool(_KEY_RE.fullmatch(value)), new_key,
                           secret=True)
