"""Pure JSONL session parsing — shared by the TUI and the GUI sidecar.

No Textual imports. Returns only JSON-safe dicts.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from agent.affect import AffectRestore, AffectVector


def load_sessions(logs_dir: Path, max_sessions: int = 20) -> list[dict]:
    """Load session files from logs_dir, return newest-first (up to max_sessions).

    Supports both new (*_logs.jsonl) and old (session_*.jsonl) filename formats.
    Each returned dict has keys: path (as str), filename, started_at, model, title.
    """
    sessions: list[dict] = []
    for pattern in ("*_logs.jsonl", "session_*.jsonl"):
        for f in logs_dir.glob(pattern):
            parsed = _parse_session_file(f)
            if parsed:
                sessions.append(parsed)
    seen: set[str] = set()
    unique: list[dict] = []
    for s in sessions:
        if s["path"] not in seen:
            seen.add(s["path"])
            unique.append(s)
    unique.sort(key=lambda s: s["started_at"], reverse=True)
    return unique[:max_sessions]


def _parse_session_file(path: Path) -> dict | None:
    """Parse a JSONL session file into a JSON-safe summary dict."""
    try:
        lines = _load_jsonl(path)
    except Exception:
        return None
    start = next((ln for ln in lines if ln.get("type") == "session_start"), {})
    started_at = start.get("started_at", "")
    model = start.get("model", "?")
    title = _derive_title(path, lines)
    return {
        "path": path,
        "filename": path.name,
        "started_at": started_at,
        "model": model,
        "title": title,
    }


def _derive_title(path: Path, lines: list[dict]) -> str:
    """Return first user message (<=60 chars) as title, or the filename stem."""
    end_rec = next((ln for ln in lines if ln.get("type") == "session_end"), None)
    if end_rec:
        for msg in end_rec.get("raw_messages") or []:
            if msg.get("role") == "user":
                text = str(msg.get("content") or "").strip().replace("\n", " ")
                return text[:60] + ("…" if len(text) > 60 else "")
    stem = path.stem
    if stem.endswith("_logs"):
        stem = stem[:-5]
    return stem


def load_raw_messages(path: Path | str) -> list[dict] | None:
    """Read a session file and return its raw_messages list, or None if absent."""
    try:
        lines = _load_jsonl(path)
    except Exception:
        return None
    end_rec = next((ln for ln in lines if ln.get("type") == "session_end"), None)
    if end_rec is None:
        return None
    return end_rec.get("raw_messages") or None


def load_affect_restore(path: Path | str) -> AffectRestore | None:
    """Read the latest valid affect state from a session file, if present."""
    try:
        lines = _load_jsonl(path)
    except Exception:
        return None

    affect_init = next((line for line in lines if line.get("type") == "affect_init"), None)
    if affect_init is None:
        return None

    latest_valid, warned = _latest_valid_affect_record(affect_init, lines)
    try:
        return _parse_affect_restore(affect_init, latest_valid)
    except ValueError:
        if not warned:
            warnings.warn("Malformed affect record in session history", UserWarning)
        return None


def _latest_valid_affect_record(init: dict, lines: list[dict]) -> tuple[dict, bool]:
    latest_valid = init
    warned = False
    for line in lines:
        if not str(line.get("type", "")).startswith("affect_"):
            continue
        try:
            _parse_affect_restore(init, line)
        except ValueError:
            if not warned:
                warnings.warn("Malformed affect record in session history", UserWarning)
                warned = True
            continue
        latest_valid = line
    return latest_valid, warned


def _load_jsonl(path: Path | str) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _parse_affect_restore(init: dict, latest: dict) -> AffectRestore:
    baseline = _parse_affect_vector(init.get("payload"), "baseline")
    current = _parse_affect_vector(latest.get("payload"), "current")
    emote_id = latest.get("payload", {}).get("emote_id")
    if emote_id is not None and not isinstance(emote_id, str):
        raise ValueError("emote_id must be a string or null")
    return AffectRestore(baseline=baseline, current=current, emote_id=emote_id)


def _parse_affect_vector(payload: object, key: str) -> AffectVector:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    values = payload.get(key)
    if not isinstance(values, list) or len(values) != 3:
        raise ValueError(f"{key} must contain three numeric values")
    return AffectVector(*values)


def build_turn_list(raw_messages: list[dict]) -> list[dict]:
    """Build a list of user-turn dicts from raw_messages for display.

    Each dict: {"index": int, "label": str, "content": str}
    Only user-role messages are returned (the turn entry points).
    """
    turns: list[dict] = []
    for i, msg in enumerate(raw_messages):
        if msg.get("role") == "user":
            content = str(msg.get("content") or "").strip().replace("\n", " ")
            label = content[:70] + ("…" if len(content) > 70 else "")
            turns.append({"index": i, "label": label, "content": content})
    return turns


def build_copyable_messages(messages: list[dict]) -> list[dict]:
    """Extract copyable user/assistant messages from a raw_messages list.

    Returns list of {label, content} dicts, oldest-first.
    Skips system messages, tool messages, tool-call-only assistant turns,
    and compaction summaries.
    """
    items = []
    for msg in messages:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            text = " ".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        elif content:
            text = str(content)
        else:
            continue
        text = text.strip()
        if not text or text.startswith("[CONTEXT SUMMARY"):
            continue
        role_label = "You" if role == "user" else "DAGI"
        preview = text[:72].replace("\n", " ")
        if len(text) > 72:
            preview += "…"
        items.append({"label": f"[{role_label}]  {preview}", "content": text})
    return items
