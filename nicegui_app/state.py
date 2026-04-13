from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    # ── Conversation data ──────────────────────────────────────────────────────
    messages: list = field(default_factory=list)         # UI message dicts
    conversation_msgs: list = field(default_factory=list) # raw OpenAI messages for multi-turn
    system_parts: list = field(default_factory=list)      # labeled system prompt sections

    # ── Agent run state ────────────────────────────────────────────────────────
    agent_running: bool = False
    stop_event: threading.Event = field(default_factory=threading.Event)
    current_asst_ui_msg: dict | None = None

    # ── Token / cost stats ─────────────────────────────────────────────────────
    total_input_tok: int = 0
    total_output_tok: int = 0
    total_cost: float = 0.0
    current_iter: int = 0
    max_iter: int = 20

    # ── Settings ───────────────────────────────────────────────────────────────
    selected_model_id: str = ""
    show_debug: bool = False

    # ── Session ────────────────────────────────────────────────────────────────
    current_thread_id: str | None = None
    history_sessions: list = field(default_factory=list)

    # ── Asyncio event loop (captured once at @ui.page load) ───────────────────
    _loop: asyncio.AbstractEventLoop | None = None

    # ── Active assistant message view (NiceGUI element refs) ──────────────────
    current_assistant_view: Any | None = None

    # ── Sidebar UI element refs for live updates ──────────────────────────────
    tok_label: Any | None = None
    cost_label: Any | None = None
    iter_label: Any | None = None
    iter_bar: Any | None = None
    iter_row: Any | None = None       # row containing iter label + bar (hidden when idle)
    stop_btn: Any | None = None
    input_field: Any | None = None
    chat_column: Any | None = None
    empty_state: Any | None = None
    history_column: Any | None = None
    export_row: Any | None = None
    chat_scroll: Any | None = None
    api_panel: Any | None = None       # right panel column element
    api_panel_html: Any | None = None  # ui.html inside the panel (live-updated)
