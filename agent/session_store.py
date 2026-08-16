"""agent/session_store.py — JSONL durability for the session event log.

One header line, then one line per event. Events are appended as they
commit so a crashed process leaves a readable log — recovery is the
feature this file exists for, and a write-on-exit design cannot deliver it.

Format:
    {"format": 1, "kind": "dagi-session-log"}
    {"seq": 1, "time": "...", "type": "request/header", "data": {...}}
    ...
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from agent import session_events as ev
from agent.session_log import SessionEvent

_HEADER = {"format": ev.SESSION_FORMAT_VERSION, "kind": "dagi-session-log"}


class IncompatibleFormat(RuntimeError):
    """The file is not a session log, or is newer than this runtime."""


def _dump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def write_session(path: Path, events: Sequence[SessionEvent]) -> None:
    """Write a complete log, replacing any existing file."""
    lines = [_dump(_HEADER)]
    lines.extend(_dump(e.to_json()) for e in events)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_event(path: Path, event: SessionEvent) -> None:
    """Append one event, writing the JSONL header first if the file is new.

    Safe to call many times on the same path: the header is written only
    when the file does not exist or is empty.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8") as handle:
        if fresh:
            handle.write(_dump(_HEADER) + "\n")
        handle.write(_dump(event.to_json()) + "\n")


def _check_header(line: str) -> None:
    """Validate the first line of a session file.

    Raises :class:`IncompatibleFormat` if the line is not a valid session
    log header or if the format version exceeds what this runtime supports.
    The version gate is intentionally strict: a future format may have
    changed event shapes that we would misread, so we reject rather than
    guess.
    """
    try:
        header = json.loads(line)
    except json.JSONDecodeError as exc:
        raise IncompatibleFormat(f"not a session log: {line.strip()[:40]!r}") from exc
    if header.get("kind") != _HEADER["kind"]:
        raise IncompatibleFormat(
            f"not a session log: missing or wrong kind marker in {line.strip()[:40]!r}"
        )
    version = header.get("format")
    if not isinstance(version, int) or version > ev.SESSION_FORMAT_VERSION:
        raise IncompatibleFormat(
            f"session log format {version} is newer than this runtime "
            f"(supports up to {ev.SESSION_FORMAT_VERSION}). "
            "Upgrade DAGI to read this log — session logs are never migrated."
        )


def read_session(path: Path) -> list[SessionEvent]:
    """Load a session log from *path*.

    Returns an empty list for a nonexistent or empty file. Drops a trailing
    partial line left by a crash mid-write rather than raising — the partial
    line signals the event was in-flight, which Phase 4 crash repair handles.
    Any parse error on a non-final line raises, because that indicates real
    corruption rather than a clean truncation.
    """
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    _check_header(lines[0])

    events: list[SessionEvent] = []
    last_idx = len(lines) - 1
    for idx in range(1, len(lines)):
        line = lines[idx]
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            if idx == last_idx:
                # Partial final line — crash truncation; safe to drop.
                break
            raise
        events.append(SessionEvent.from_json(raw))
    return events
