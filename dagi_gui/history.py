"""GUI history adapter — wraps agent/history.py to return JSON-safe dicts.

Never imports Textual. Path objects are serialized to strings.
"""

from __future__ import annotations

from pathlib import Path

from agent.history import (
    build_turn_list,
    load_raw_messages,
    load_sessions as _load_sessions,
)


def list_session_summaries(logs_dir: Path, limit: int = 20) -> list[dict]:
    """Return JSON-safe session summaries, newest-first."""
    sessions = _load_sessions(logs_dir, max_sessions=limit)
    return [_serialize_session(s) for s in sessions]


def _serialize_session(session: dict) -> dict:
    """Convert Path values to strings for JSON serialization."""
    return {
        **session,
        "path": str(session["path"]),
    }


def restore_messages(
    path: str | Path, turn_index: int
) -> dict:
    """Load raw_messages up to turn_index; return renderable messages and metadata.

    turn_index is the position in raw_messages (not the user-turn number).
    Pass len(raw_messages) to restore the full session.
    """
    raw = load_raw_messages(Path(path))
    if raw is None:
        return {"error": "session file not found or has no raw_messages", "messages": []}

    sliced = raw[:turn_index] if turn_index < len(raw) else raw
    turns = build_turn_list(sliced)

    renderable = [
        {"role": msg["role"], "content": _extract_text(msg)}
        for msg in sliced
        if msg.get("role") in ("user", "assistant")
        and _extract_text(msg)
    ]

    return {
        "raw_messages": sliced,
        "renderable": renderable,
        "turns": turns,
    }


def _extract_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, list):
        return " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
    return str(content or "").strip()
