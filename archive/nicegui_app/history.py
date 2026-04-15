"""
nicegui_app/history.py
──────────────────────
Session history helpers — ported directly from app.py with no Streamlit dependencies.
These functions are safe to call from asyncio via run.io_bound() since they do
synchronous file I/O.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from archive.nicegui_app.state import AppState


# ── Parsing ───────────────────────────────────────────────────────────────────

def _session_title(messages: list) -> str:
    """Return the first user message truncated to 50 chars, or empty string."""
    for msg in messages:
        if msg.get("entity") == "user" and msg.get("content"):
            text = msg["content"].strip().replace("\n", " ")
            return text[:50] + ("…" if len(text) > 50 else "")
    return ""


def _parse_jsonl(filepath: Path) -> dict | None:
    """Parse a JSONL session file into a normalised session dict."""
    try:
        lines = [
            json.loads(line)
            for line in filepath.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception:
        return None

    start_rec = next((l for l in lines if l.get("type") == "session_start"), {})
    end_rec   = next((l for l in lines if l.get("type") == "session_end"), None)
    messages  = [l for l in lines if l.get("type") == "message"]

    thread_id  = start_rec.get("thread_id", filepath.name)
    started_at = start_rec.get("started_at", "")
    meta: dict = {
        "model":      start_rec.get("model", "?"),
        "started_at": started_at,
        "thread_id":  thread_id,
    }
    if end_rec:
        meta.update({
            "finished_at":         end_rec.get("finished_at", ""),
            "total_input_tokens":  end_rec.get("total_input_tokens", 0),
            "total_output_tokens": end_rec.get("total_output_tokens", 0),
            "total_cost":          end_rec.get("total_cost"),
            "tool_call_counts":    end_rec.get("tool_call_counts", {}),
        })

    raw_messages = end_rec.get("raw_messages") if end_rec else None
    return {
        "filename":     filepath.name,
        "filepath":     str(filepath),
        "started_at":   started_at,
        "meta":         meta,
        "messages":     messages,
        "raw_messages": raw_messages,
        "has_raw":      raw_messages is not None,
    }


def load_history_sessions() -> list[dict]:
    """
    Load all session files from logs/, group by thread_id, return newest-first.
    Designed to be called via run.io_bound() from async context.
    """
    logs = Path("logs")
    if not logs.exists():
        return []

    raw_sessions: list[dict] = []

    for f in logs.glob("session_*.jsonl"):
        parsed = _parse_jsonl(f)
        if parsed:
            raw_sessions.append(parsed)

    for f in logs.glob("session_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            tid = data.get("meta", {}).get("thread_id", f.name)
            started_at = data.get("meta", {}).get("started_at", "")
            raw_sessions.append({
                "filename":     f.name,
                "filepath":     str(f),
                "started_at":   started_at,
                "meta":         data.get("meta", {}),
                "messages":     data.get("messages", []),
                "raw_messages": data.get("raw_messages"),
                "has_raw":      "raw_messages" in data,
            })
        except Exception:
            continue

    # Group by thread_id
    threads: dict[str, dict] = {}
    for sess in raw_sessions:
        tid = sess["meta"].get("thread_id") or sess["filename"]
        if tid not in threads:
            threads[tid] = {"thread_id": tid, "title": "", "sessions": []}
        threads[tid]["sessions"].append(sess)

    # Sort sessions within each thread oldest→newest; derive title
    for thread in threads.values():
        thread["sessions"].sort(key=lambda s: s.get("started_at", ""))
        for sess in thread["sessions"]:
            title = _session_title(sess["messages"])
            if title:
                thread["title"] = title
                break
        if not thread["title"]:
            ts = thread["sessions"][0].get("started_at", "?")[:16].replace("T", " ")
            thread["title"] = ts

    thread_list = list(threads.values())
    thread_list.sort(key=lambda t: t["sessions"][-1].get("started_at", ""), reverse=True)
    return thread_list


# ── Session continuation ──────────────────────────────────────────────────────

def build_ui_messages_from_session(sess: dict) -> list[dict]:
    """
    Convert JSONL session MessageNode records into the UI message dict format.
    Returns a list ready to be assigned to state.messages.
    """
    ui_messages = []
    for node in sess.get("messages", []):
        entity = node.get("entity", "")
        if entity == "system":
            continue
        if entity == "user":
            ui_messages.append({
                "role": "user",
                "content": node.get("content") or "",
                "tool_calls": [],
                "input_tokens": None,
                "output_tokens": None,
                "cost": None,
                "timestamp": node.get("timestamp", ""),
                "api_snapshot": None,
                "reasoning": None,
            })
        elif entity == "assistant":
            ui_messages.append({
                "role": "assistant",
                "content": node.get("content"),
                "tool_calls": [
                    {
                        "name": tc.get("name", ""),
                        "description": tc.get("description", ""),
                        "input": tc.get("input", "{}"),
                        "result": tc.get("result", ""),
                        "status": "done",
                    }
                    for tc in node.get("tool_calls", [])
                ],
                "input_tokens": node.get("input_tokens"),
                "output_tokens": node.get("output_tokens"),
                "cost": node.get("cost"),
                "timestamp": node.get("timestamp", ""),
                "api_snapshot": None,
                "reasoning": None,
            })
    return ui_messages


def apply_session_to_state(state: "AppState", sess: dict, thread_id: str) -> bool:
    """
    Load a past session into state for continuation.
    Returns False if the session lacks raw_messages (old format).
    """
    raw = sess.get("raw_messages")
    if not raw:
        return False

    meta = sess.get("meta", {})
    state.messages = build_ui_messages_from_session(sess)
    state.conversation_msgs = raw
    state.current_thread_id = thread_id
    state.system_parts = []
    state.agent_running = False
    state.total_input_tok = meta.get("total_input_tokens", 0) or 0
    state.total_output_tok = meta.get("total_output_tokens", 0) or 0
    state.total_cost = meta.get("total_cost") or 0.0
    state.current_iter = 0
    state.current_assistant_view = None
    state.current_asst_ui_msg = None
    return True
