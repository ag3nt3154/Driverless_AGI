"""
dagi — Streamlit Chat UI
Run with: conda run -n dagi streamlit run app.py
"""
from __future__ import annotations

import difflib
import json
import queue
import threading
from datetime import datetime
from pathlib import Path

import streamlit as st
import yaml
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

from agent.loop import AgentCallbacks, AgentConfig, AgentLoop
from agent.registry import registry
import agent.tools  # noqa: F401 — registers tools as side-effect

load_dotenv()

# ─── Page config (must be first Streamlit call) ───────────────────────────────
st.set_page_config(
    page_title="dagi",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS: Soft Structuralism — light, airy, Apple-tier ───────────────────────
# st.html() is used (not st.markdown) because Streamlit 1.36+ strips <style>
# tags from markdown even with unsafe_allow_html=True.
st.html("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
<style>

/* ── Reset & Base ── */
*, *::before, *::after { box-sizing: border-box; }

html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif !important;
    background: #F2F2F7 !important;
    color: #1C1C1E !important;
}

/* ── Hide Streamlit Chrome ── */
footer { display: none !important; }

/* Hide decoration bar but keep sidebar collapse/expand control visible */
[data-testid="stDecoration"] { display: none !important; }
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"] { display: flex !important; }

/* ── Sidebar ── */
[data-testid="stSidebar"],
[data-testid="stSidebarContent"],
section[data-testid="stSidebar"] > div {
    background: #FFFFFF !important;
    border-right: 1px solid rgba(60,60,67,0.08) !important;
    box-shadow: 2px 0 20px rgba(0,0,0,0.04) !important;
}
[data-testid="stSidebar"] * {
    font-family: 'Plus Jakarta Sans', system-ui, sans-serif !important;
    color: #1C1C1E !important;
}
[data-testid="stSidebar"] .material-icons,
[data-testid="stSidebar"] .material-icons-outlined,
[data-testid="stSidebar"] .material-icons-round,
[data-testid="stSidebar"] .material-icons-sharp {
    font-family: 'Material Icons', 'Material Icons Outlined', 'Material Icons Round', 'Material Icons Sharp' !important;
}
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small { color: #8E8E93 !important; }
[data-testid="stSidebar"] hr {
    border: none !important;
    border-top: 1px solid rgba(60,60,67,0.1) !important;
}

/* Sidebar buttons */
[data-testid="stSidebar"] .stButton > button {
    background: #F2F2F7 !important;
    color: #1C1C1E !important;
    border: 1px solid rgba(60,60,67,0.12) !important;
    border-radius: 10px !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
    transition: all 400ms cubic-bezier(0.32,0.72,0,1) !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #FFFFFF !important;
    border-color: rgba(0,122,255,0.5) !important;
    color: #007AFF !important;
    box-shadow: 0 2px 10px rgba(0,122,255,0.1) !important;
    transform: translateY(-1px) !important;
}
[data-testid="stSidebar"] .stButton > button:active {
    transform: scale(0.97) !important;
}

/* ── Stat Boxes (Double-Bezel) ── */
.stat-box {
    background: rgba(60,60,67,0.04);
    border: 1px solid rgba(60,60,67,0.08);
    border-radius: 14px;
    padding: 3px;
    margin: 6px 0;
}
.stat-box-inner {
    background: #FFFFFF;
    border-radius: 11px;
    padding: 10px 13px;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.9), 0 1px 4px rgba(0,0,0,0.04);
}
.stat-label {
    color: #8E8E93;
    font-size: 0.67rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-weight: 600;
    font-family: 'Plus Jakarta Sans', sans-serif;
}
.stat-val {
    color: #1C1C1E;
    font-size: 0.9rem;
    font-weight: 600;
    font-family: 'Plus Jakarta Sans', sans-serif;
    margin-top: 2px;
}

/* ── Message Bubbles (Double-Bezel) ── */
.user-bubble-shell {
    background: rgba(0,122,255,0.08);
    border: 1px solid rgba(0,122,255,0.14);
    border-radius: 18px 18px 4px 18px;
    padding: 2px;
    margin: 10px 0 4px auto;
    max-width: 70%;
    width: fit-content;
    word-break: break-word;
}
.user-bubble {
    background: #007AFF;
    border-radius: 16px 16px 2px 16px;
    padding: 10px 16px;
    color: #FFFFFF !important;
    font-size: 0.9rem;
    line-height: 1.55;
    font-family: 'Plus Jakarta Sans', sans-serif;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.2);
}

.assistant-bubble-shell {
    background: rgba(60,60,67,0.03);
    border: 1px solid rgba(60,60,67,0.08);
    border-radius: 4px 18px 18px 18px;
    padding: 2px;
    margin: 10px auto 4px 0;
    max-width: 84%;
    word-break: break-word;
}
.assistant-bubble {
    background: #FFFFFF;
    border-radius: 2px 16px 16px 16px;
    padding: 12px 16px;
    color: #1C1C1E !important;
    font-size: 0.9rem;
    line-height: 1.65;
    font-family: 'Plus Jakarta Sans', sans-serif;
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,1),
        0 2px 8px rgba(0,0,0,0.05),
        0 8px 28px rgba(0,0,0,0.04);
}
.assistant-bubble p,
.assistant-bubble li,
.assistant-bubble span { color: #1C1C1E !important; }

.msg-meta {
    font-size: 0.67rem;
    color: #AEAEB2;
    margin-top: 3px;
    margin-bottom: 8px;
    font-family: 'Plus Jakarta Sans', sans-serif;
}

/* ── Tool Call Expanders (Double-Bezel card feel) ── */
[data-testid="stExpander"] {
    background: rgba(60,60,67,0.03) !important;
    border: 1px solid rgba(60,60,67,0.1) !important;
    border-left: 2px solid #007AFF !important;
    border-radius: 10px !important;
    margin: 4px 0 !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;
    transition: box-shadow 400ms cubic-bezier(0.32,0.72,0,1),
                transform 400ms cubic-bezier(0.32,0.72,0,1) !important;
}
[data-testid="stExpander"]:hover {
    box-shadow: 0 4px 16px rgba(0,0,0,0.08) !important;
    transform: translateY(-1px) !important;
}
[data-testid="stExpander"] details summary p,
[data-testid="stExpander"] summary span,
[data-testid="stExpander"] summary {
    font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace !important;
    font-size: 0.79rem !important;
    color: #007AFF !important;
}

/* Running expander — amber left-border */
.tool-running > [data-testid="stExpander"] {
    border-left-color: #FF9500 !important;
}

/* ── Chat Input (floating island) ── */
[data-testid="stChatInput"] {
    background: #FFFFFF !important;
    border: 1px solid rgba(60,60,67,0.14) !important;
    border-radius: 16px !important;
    box-shadow:
        0 2px 8px rgba(0,0,0,0.04),
        0 8px 32px rgba(0,0,0,0.06) !important;
    transition: box-shadow 400ms cubic-bezier(0.32,0.72,0,1) !important;
}
[data-testid="stChatInput"]:focus-within {
    box-shadow:
        0 0 0 3px rgba(0,122,255,0.12),
        0 4px 16px rgba(0,0,0,0.08) !important;
    border-color: rgba(0,122,255,0.4) !important;
}
[data-testid="stChatInput"] textarea {
    background: transparent !important;
    color: #1C1C1E !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-size: 0.9rem !important;
}
[data-testid="stChatInput"] textarea::placeholder { color: #AEAEB2 !important; }

/* ── Global Typography ── */
p, li, label, div, span {
    font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
    color: #1C1C1E;
}
h1, h2, h3, strong {
    font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
    color: #1C1C1E;
    font-weight: 700;
}

/* ── Code Blocks ── */
code, pre {
    font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace !important;
    border-radius: 6px !important;
}
[data-testid="stCodeBlock"] pre,
[data-testid="stCodeBlock"] {
    background: #F7F7F8 !important;
    border: 1px solid rgba(60,60,67,0.1) !important;
    border-radius: 10px !important;
    color: #1C1C1E !important;
}

/* ── Progress Bar ── */
[data-testid="stProgressBar"] > div {
    background: rgba(0,122,255,0.12) !important;
    border-radius: 99px !important;
}
[data-testid="stProgressBar"] > div > div {
    background: linear-gradient(90deg, #007AFF 0%, #34AADC 100%) !important;
    border-radius: 99px !important;
}

/* ── Download Button ── */
[data-testid="stDownloadButton"] > button {
    background: #F2F2F7 !important;
    border: 1px solid rgba(60,60,67,0.12) !important;
    border-radius: 10px !important;
    color: #007AFF !important;
    font-weight: 500 !important;
    font-size: 0.8rem !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    transition: all 400ms cubic-bezier(0.32,0.72,0,1) !important;
}
[data-testid="stDownloadButton"] > button:hover {
    background: rgba(0,122,255,0.06) !important;
    border-color: rgba(0,122,255,0.4) !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(0,122,255,0.14) !important;
}

/* ── Popover / Settings ── */
[data-testid="stPopover"] > button {
    background: #F2F2F7 !important;
    border: 1px solid rgba(60,60,67,0.12) !important;
    border-radius: 10px !important;
    color: #8E8E93 !important;
    transition: all 400ms cubic-bezier(0.32,0.72,0,1) !important;
}
[data-testid="stPopover"] > button:hover {
    color: #007AFF !important;
    border-color: rgba(0,122,255,0.4) !important;
    background: rgba(0,122,255,0.04) !important;
}

/* ── Text Inputs (settings) ── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background: #F7F7F8 !important;
    border: 1px solid rgba(60,60,67,0.14) !important;
    border-radius: 10px !important;
    color: #1C1C1E !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    transition: all 300ms cubic-bezier(0.32,0.72,0,1) !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus {
    border-color: #007AFF !important;
    box-shadow: 0 0 0 3px rgba(0,122,255,0.1) !important;
    background: #FFFFFF !important;
}

/* ── Dividers ── */
hr {
    border: none !important;
    border-top: 1px solid rgba(60,60,67,0.1) !important;
    margin: 12px 0 !important;
}

/* ── Stop button (destructive) ── */
button[kind="secondary"] {
    background: rgba(255,59,48,0.05) !important;
    border: 1px solid rgba(255,59,48,0.2) !important;
    color: #FF3B30 !important;
    border-radius: 10px !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    transition: all 400ms cubic-bezier(0.32,0.72,0,1) !important;
}
button[kind="secondary"]:hover {
    background: rgba(255,59,48,0.1) !important;
    border-color: #FF3B30 !important;
    transform: scale(0.98) !important;
}

</style>
""")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_config() -> AgentConfig:
    cfg_path = Path("config.yaml")
    overrides: dict = {}
    if cfg_path.exists():
        overrides = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return AgentConfig(
        model=overrides.get("model", "gpt-4o"),
        base_url=overrides.get("base_url", "https://api.openai.com/v1"),
        max_iterations=overrides.get("max_iterations", 20),
    )


def _save_config(model: str, base_url: str, max_iter: int) -> None:
    Path("config.yaml").write_text(
        yaml.dump({"model": model, "base_url": base_url, "max_iterations": max_iter}),
        encoding="utf-8",
    )


def _session_title(messages: list) -> str:
    """Return the first user message truncated to 50 chars, or empty string."""
    for msg in messages:
        if msg.get("entity") == "user" and msg.get("content"):
            text = msg["content"].strip().replace("\n", " ")
            return text[:50] + ("\u2026" if len(text) > 50 else "")
    return ""


def _parse_jsonl(filepath: Path) -> dict | None:
    """Parse a JSONL session file into a normalised session dict."""
    try:
        lines = [json.loads(l) for l in filepath.read_text(encoding="utf-8").splitlines() if l.strip()]
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
            "finished_at":        end_rec.get("finished_at", ""),
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
    """Load all session files, group by thread_id, return newest-first thread list."""
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

    # Sort threads newest-first by latest session's started_at
    thread_list = list(threads.values())
    thread_list.sort(key=lambda t: t["sessions"][-1].get("started_at", ""), reverse=True)
    return thread_list


def _tool_summary(tc: dict) -> str:
    name = tc["name"]
    try:
        args = json.loads(tc["input"])
    except Exception:
        args = {}
    if name == "bash":
        cmd = args.get("command", "")
        return f"bash  {cmd[:70]}{'…' if len(cmd) > 70 else ''}"
    elif name == "read":
        return f"read  {args.get('path', '')}"
    elif name == "write":
        path = args.get("path", "")
        chars = len(args.get("content", ""))
        return f"write  {path}  ({chars} chars)"
    elif name == "edit":
        return f"edit  {args.get('path', '')}"
    return f"{name}  {str(args)[:70]}"


def _last_assistant_msg() -> dict:
    msgs = st.session_state.messages
    for msg in reversed(msgs):
        if msg["role"] == "assistant":
            return msg
    # create one if none exists yet (first tool_start fires before assistant_text)
    new_msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [],
        "input_tokens": None,
        "output_tokens": None,
        "cost": None,
        "timestamp": datetime.utcnow().isoformat(),
        "api_snapshot": None,
        "reasoning": None,
    }
    msgs.append(new_msg)
    return new_msg


# ─── State initialisation ─────────────────────────────────────────────────────

def _init_state() -> None:
    if "initialized" in st.session_state:
        return
    st.session_state.initialized       = True
    st.session_state.messages          = []
    st.session_state.conversation_msgs = []   # raw OpenAI _messages for multi-turn
    st.session_state.system_parts      = []   # labeled system prompt sections for API payload expander
    st.session_state.agent_running     = False
    st.session_state.agent_thread      = None
    st.session_state.event_queue       = queue.SimpleQueue()
    st.session_state.total_input_tok   = 0
    st.session_state.total_output_tok  = 0
    st.session_state.total_cost        = 0.0
    st.session_state.current_iter      = 0
    st.session_state.max_iter          = _load_config().max_iterations
    st.session_state.history_sessions  = load_history_sessions()
    st.session_state.current_thread_id = None
    st.session_state.stop_event        = threading.Event()


_init_state()


# ─── Event queue drain (runs on every Streamlit rerun) ───────────────────────

def drain_event_queue() -> None:
    q: queue.SimpleQueue = st.session_state.event_queue
    while not q.empty():
        ev = q.get_nowait()
        t = ev.get("type")

        if t == "tool_start":
            _last_assistant_msg()["tool_calls"].append({
                "name":        ev["name"],
                "description": ev["description"],
                "input":       ev["args"],
                "result":      "",
                "status":      "running",
            })

        elif t == "tool_end":
            msg = _last_assistant_msg()
            if msg["tool_calls"]:
                tc = msg["tool_calls"][-1]
                tc["result"] = ev["result"]
                tc["status"] = "done"

        elif t == "assistant_text":
            _last_assistant_msg()["content"] = ev["text"]

        elif t == "token_update":
            st.session_state.total_input_tok  += ev.get("input_tokens", 0) or 0
            st.session_state.total_output_tok += ev.get("output_tokens", 0) or 0
            if ev.get("cost"):
                st.session_state.total_cost += ev["cost"]

        elif t == "iteration":
            st.session_state.current_iter = ev["current"]
            st.session_state.max_iter = ev["maximum"]

        elif t == "session_update":
            # safe: main thread applies the write
            st.session_state.conversation_msgs = ev["messages"]

        elif t == "done":
            st.session_state.agent_running = False
            st.session_state.current_iter = 0
            # refresh history list to include newly saved session
            st.session_state.history_sessions = load_history_sessions()

        elif t == "api_snapshot":
            _last_assistant_msg()["api_snapshot"] = ev["messages"]

        elif t == "reasoning":
            _last_assistant_msg()["reasoning"] = ev["text"]

        elif t == "error":
            st.session_state.agent_running = False
            st.session_state.current_iter = 0
            _last_assistant_msg()["content"] = f"⚠ Error: {ev['error']}"


drain_event_queue()


# ─── Agent thread launcher ────────────────────────────────────────────────────

def start_agent_thread(task: str) -> None:
    stop_event: threading.Event = st.session_state.stop_event
    stop_event.clear()
    q: queue.SimpleQueue = st.session_state.event_queue

    callbacks = AgentCallbacks(
        on_tool_start=lambda n, d, a: q.put({"type": "tool_start", "name": n, "description": d, "args": a}),
        on_tool_end=lambda n, r: q.put({"type": "tool_end", "name": n, "result": r}),
        on_assistant_text=lambda t: q.put({"type": "assistant_text", "text": t}),
        on_token_update=lambda i, o, c: q.put({"type": "token_update", "input_tokens": i, "output_tokens": o, "cost": c}),
        on_iteration=lambda cur, mx: q.put({"type": "iteration", "current": cur, "maximum": mx}),
        on_done=lambda r: q.put({"type": "done", "result": r}),
        on_error=lambda e: q.put({"type": "error", "error": str(e)}),
        on_api_call=lambda msgs: q.put({"type": "api_snapshot", "messages": msgs}),
        on_reasoning=lambda t: q.put({"type": "reasoning", "text": t}),
    )

    cfg = _load_config()
    cfg.thread_id = st.session_state.get("current_thread_id")
    prior = st.session_state.conversation_msgs or None
    loop = AgentLoop(cfg, registry, callbacks, initial_messages=prior)
    st.session_state.system_parts      = loop.system_parts
    st.session_state.current_thread_id = loop.tracker.thread_id

    def _run() -> None:
        try:
            loop.run(task)
        finally:
            # Always route messages back through queue — never write session_state directly
            q.put({"type": "session_update", "messages": loop._messages})

    st.session_state.agent_running = True
    t = threading.Thread(target=_run, daemon=True)
    st.session_state.agent_thread = t
    t.start()


def continue_session(sess: dict, thread_id: str) -> None:
    """Load a past session's raw_messages into active state for continuation."""
    raw = sess.get("raw_messages")
    if not raw:
        st.error("This session has no raw_messages — cannot continue (old format).")
        return

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

    meta = sess.get("meta", {})
    st.session_state.messages          = ui_messages
    st.session_state.conversation_msgs = raw
    st.session_state.current_thread_id = thread_id
    st.session_state.system_parts      = []
    st.session_state.event_queue       = queue.SimpleQueue()
    st.session_state.agent_running     = False
    st.session_state.total_input_tok   = meta.get("total_input_tokens", 0) or 0
    st.session_state.total_output_tok  = meta.get("total_output_tokens", 0) or 0
    st.session_state.total_cost        = meta.get("total_cost") or 0.0
    st.session_state.current_iter      = 0
    st.session_state.stop_event        = threading.Event()



# ─── Message rendering ────────────────────────────────────────────────────────

def render_tool_call(tc: dict) -> None:
    icon = "⟳" if tc["status"] == "running" else "✓"
    label = _tool_summary(tc)
    expanded = tc["status"] == "running"

    with st.expander(f"{icon}  {label}", expanded=expanded):
        # Input args
        try:
            args_pretty = json.dumps(json.loads(tc["input"]), indent=2)
        except Exception:
            args_pretty = tc["input"]
        st.code(args_pretty, language="json")

        if tc["status"] == "done" and tc["result"]:
            result = tc["result"]
            if result.startswith("__list__:"):
                try:
                    data = json.loads(result[len("__list__:"):])
                    imgs = data if isinstance(data, list) else [data]
                    for img in imgs:
                        st.image(img)
                except Exception:
                    st.code(result[:2000])
            elif tc["name"] == "edit":
                # Show a diff for edit tool calls
                try:
                    args = json.loads(tc["input"])
                    old = args.get("oldText", "")
                    new = args.get("newText", "")
                    diff = "\n".join(difflib.unified_diff(
                        old.splitlines(), new.splitlines(),
                        fromfile="before", tofile="after", lineterm=""
                    ))
                    st.code(diff or result[:2000], language="diff")
                except Exception:
                    st.code(result[:2000])
            else:
                st.code(result[:3000], language="bash")


def _format_api_payload_text(snapshot: list, system_parts: list[dict]) -> str:
    """Build a human-readable text transcript of the full API messages array."""
    SEP = "═" * 64
    lines: list[str] = []
    for part in system_parts:
        lines += [SEP, f"  SYSTEM › {part['label']}", SEP, part["content"], ""]
    for m in snapshot:
        role = m.get("role", "")
        if role == "system":
            continue
        if role == "user":
            lines += [SEP, "  USER", SEP, m.get("content") or "", ""]
        elif role == "assistant":
            tcs = m.get("tool_calls")
            lines += [SEP, "  ASSISTANT" + (" + TOOL CALLS" if tcs else ""), SEP]
            if m.get("content"):
                lines.append(m["content"])
            if tcs:
                for tc in tcs:
                    fn = tc.get("function", {})
                    lines.append(f"  → {fn.get('name', '')}({fn.get('arguments', '')})")
            lines.append("")
        elif role == "tool":
            lines += [SEP, "  TOOL RESULT", SEP]
            c = m.get("content") or ""
            lines.append(c[:800] + ("…" if len(c) > 800 else ""))
            lines.append("")
    return "\n".join(lines)


def render_payload_expander(snapshot: list, system_parts: list[dict]) -> None:
    with st.expander("📋 Full API Payload", expanded=False):
        st.code(_format_api_payload_text(snapshot, system_parts), language="text")


def render_tool_calls_expander(tool_calls: list) -> None:
    if not tool_calls:
        return
    with st.expander(f"🔧 Tool Calls ({len(tool_calls)})", expanded=False):
        items = "\n".join(
            f"{i}. `{tc['name']}` — {tc.get('description', '')}"
            for i, tc in enumerate(tool_calls, 1)
        )
        st.markdown(items)


def render_reasoning_expander(reasoning: str | None) -> None:
    if not reasoning:
        return
    with st.expander("🧠 Model Reasoning", expanded=False):
        st.markdown(reasoning)


def render_message(msg: dict) -> None:
    role = msg["role"]
    content = msg.get("content") or ""
    tool_calls = msg.get("tool_calls", [])
    ts = msg.get("timestamp", "")[:16].replace("T", " ")

    if role == "user":
        st.markdown(
            f'<div class="user-bubble-shell"><div class="user-bubble">{content}</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(f'<div class="msg-meta" style="text-align:right">{ts}</div>', unsafe_allow_html=True)
    elif role == "assistant":
        with st.container():
            render_reasoning_expander(msg.get("reasoning"))
            if msg.get("api_snapshot") is not None:
                render_payload_expander(msg["api_snapshot"], st.session_state.get("system_parts", []))
            render_tool_calls_expander(tool_calls)
            for tc in tool_calls:
                render_tool_call(tc)
            st.markdown('<div class="assistant-bubble-shell"><div class="assistant-bubble">', unsafe_allow_html=True)
            if content:
                st.markdown(content)
            st.markdown("</div></div>", unsafe_allow_html=True)
            tok_info = ""
            if msg.get("input_tokens") or msg.get("output_tokens"):
                tok_info = f" · {msg.get('input_tokens',0)}↑ {msg.get('output_tokens',0)}↓"
            if msg.get("cost"):
                tok_info += f" · ${msg['cost']:.5f}"
            if tok_info or ts:
                st.markdown(f'<div class="msg-meta">{ts}{tok_info}</div>', unsafe_allow_html=True)



# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("＋ New Chat", use_container_width=True):
            st.session_state.messages          = []
            st.session_state.conversation_msgs = []
            st.session_state.system_parts      = []
            st.session_state.event_queue       = queue.SimpleQueue()
            st.session_state.agent_running     = False
            st.session_state.total_input_tok   = 0
            st.session_state.total_output_tok  = 0
            st.session_state.total_cost        = 0.0
            st.session_state.current_iter      = 0
            st.session_state.current_thread_id = None
            st.session_state.history_sessions  = load_history_sessions()
            st.rerun()
    with col2:
        with st.popover("⚙", use_container_width=True):
            st.markdown("**Settings**")
            cfg = _load_config()
            new_model    = st.text_input("Model", value=cfg.model, key="cfg_model")
            new_base_url = st.text_input("Base URL", value=cfg.base_url, key="cfg_base_url")
            new_max_iter = st.number_input("Max iterations", value=cfg.max_iterations,
                                           min_value=1, max_value=200, key="cfg_max_iter")
            if st.button("Save", key="cfg_save"):
                _save_config(new_model, new_base_url, int(new_max_iter))
                st.session_state.max_iter = int(new_max_iter)
                st.success("Saved.")

    st.divider()

    # Current session stats
    st.markdown("**Current Session**")
    in_tok  = st.session_state.total_input_tok
    out_tok = st.session_state.total_output_tok
    cost    = st.session_state.total_cost
    cur_i   = st.session_state.current_iter
    max_i   = st.session_state.max_iter

    st.markdown(
        f'<div class="stat-box"><div class="stat-box-inner">'
        f'<div class="stat-label">Tokens</div>'
        f'<div class="stat-val">↑ {in_tok:,} &nbsp; ↓ {out_tok:,}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="stat-box"><div class="stat-box-inner">'
        f'<div class="stat-label">Cost</div>'
        f'<div class="stat-val">${cost:.5f}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    if st.session_state.agent_running and max_i > 0:
        st.markdown(
            f'<div class="stat-label" style="margin-top:8px">Iteration {cur_i} / {max_i}</div>',
            unsafe_allow_html=True,
        )
        st.progress(cur_i / max_i)

    # Export current session
    if st.session_state.messages:
        export_data = json.dumps(
            {"messages": st.session_state.messages, "meta": {
                "total_input_tokens": in_tok,
                "total_output_tokens": out_tok,
                "total_cost": cost,
            }},
            indent=2,
        )
        st.download_button(
            "⬇ Export session",
            data=export_data,
            file_name=f"dagi_session_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True,
        )

    st.divider()

    # Past sessions — one button per thread, click to continue
    st.markdown("**Past Sessions**")
    if not st.session_state.history_sessions:
        st.caption("No past sessions yet.")

    for thread in st.session_state.history_sessions[:20]:
        tid     = thread["thread_id"]
        title   = thread["title"] or tid[:12]
        latest  = thread["sessions"][-1]
        has_raw = latest.get("has_raw", False)
        if st.button(title, key=f"sess_{tid[:16]}", use_container_width=True,
                     disabled=not has_raw,
                     help=None if has_raw else "Old format — cannot continue"):
            continue_session(latest, tid)
            st.rerun()


# ─── Main chat area ───────────────────────────────────────────────────────────
chat_container = st.container()
with chat_container:
    if not st.session_state.messages:
        st.markdown(
            '<div style="text-align:center;margin-top:14vh;">'
            '<div style="font-family:\'Plus Jakarta Sans\',sans-serif;font-size:2.2rem;'
            'font-weight:300;color:#1C1C1E;letter-spacing:-0.03em;">◈ dagi</div>'
            '<div style="font-family:\'Plus Jakarta Sans\',sans-serif;font-size:0.85rem;'
            'color:#AEAEB2;margin-top:10px;font-weight:400;">What can I help you build today?</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    for msg in st.session_state.messages:
        render_message(msg)

# Input row
input_col, stop_col = st.columns([8, 1])
with input_col:
    user_input = st.chat_input(
        "Message dagi…",
        disabled=st.session_state.agent_running,
        key="chat_input",
    )
with stop_col:
    # Vertical alignment hack via empty space
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    if st.session_state.agent_running:
        if st.button("■ Stop", use_container_width=True, type="secondary"):
            st.session_state.stop_event.set()
            st.session_state.agent_running = False
            _last_assistant_msg()["content"] = (_last_assistant_msg().get("content") or "") + "\n\n*[Stopped by user]*"
            st.rerun()

if user_input and user_input.strip():
    task = user_input.strip()
    # Add user message to UI immediately
    st.session_state.messages.append({
        "role": "user",
        "content": task,
        "tool_calls": [],
        "input_tokens": None,
        "output_tokens": None,
        "cost": None,
        "timestamp": datetime.utcnow().isoformat(),
    })
    # Prime an empty assistant message so tool_start events have somewhere to land
    st.session_state.messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [],
        "input_tokens": None,
        "output_tokens": None,
        "cost": None,
        "timestamp": datetime.utcnow().isoformat(),
        "api_snapshot": None,
        "reasoning": None,
    })
    start_agent_thread(task)
    st.rerun()

# ─── Auto-refresh while agent is running ─────────────────────────────────────
if st.session_state.get("agent_running"):
    st_autorefresh(interval=600, key="agent_poll")
