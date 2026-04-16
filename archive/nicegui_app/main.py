"""
nicegui_app/main.py
───────────────────
dagi — NiceGUI Chat UI
Run with: conda run -n dagi python -m nicegui_app.main
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from nicegui import run, ui

from agent.config_loader import resolve_model_config
from agent.loop import AgentLoop
from agent.registry import registry
import agent.tools  # noqa: F401 — registers tools as side-effect

from archive.nicegui_app.callbacks import make_callbacks
from archive.nicegui_app.components.chat_message import (
    render_assistant_message_shell,
    render_static_assistant_message,
    render_user_message,
)
from archive.nicegui_app.components.sidebar import (
    refresh_history,
    render_sidebar,
)
from archive.nicegui_app.history import apply_session_to_state, load_history_sessions
from archive.nicegui_app.state import AppState

load_dotenv()

# ── Module-level state (single-user local tool) ───────────────────────────────
state = AppState()


# ── Page ──────────────────────────────────────────────────────────────────────

@ui.page("/")
async def index() -> None:
    # Capture the running event loop — used by all callbacks
    state._loop = asyncio.get_running_loop()

    # Load history and default config on first visit
    cfg = resolve_model_config()
    state.max_iter = cfg.max_iterations
    if not state.selected_model_id:
        from agent.config_loader import load_raw_config, list_model_ids
        raw = load_raw_config()
        ids = list_model_ids()
        state.selected_model_id = raw.get("default_model", ids[0] if ids else "")
    if not state.history_sessions:
        state.history_sessions = await run.io_bound(load_history_sessions)

    # Store on_load_session on state so callbacks.py can access it for history refresh
    state._on_load_session = _handle_load_session  # type: ignore[attr-defined]

    # ── Debug toggle handler ──────────────────────────────────────────────────
    def _on_debug_toggle(value: bool) -> None:
        """Called when the debug switch is toggled. Immediately renders last snapshot."""
        state.show_debug = value
        if value and state.api_panel_html:
            snap = None
            if state.current_asst_ui_msg:
                snap = state.current_asst_ui_msg.get("api_snapshot")
            import json as _json
            content = (
                f'<pre class="api-payload-output">{_json.dumps(snap, indent=2, default=str)}</pre>'
                if snap
                else '<pre class="api-payload-output">— No call yet —</pre>'
            )
            state.api_panel_html.set_content(content)

    state._on_debug_toggle = _on_debug_toggle  # type: ignore[attr-defined]

    # ── Fonts & CSS ───────────────────────────────────────────────────────────
    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:'
        'wght@300;400;500;600;700&display=swap" rel="stylesheet">'
        # Smooth scroll + overflow fix
        '<style>html{scroll-behavior:smooth;overflow:hidden;}body{overflow:hidden;}</style>'
    )
    css_path = Path(__file__).parent / "styles" / "theme.css"
    ui.add_css(css_path.read_text(encoding="utf-8"))
    ui.query("body").style("background: #F2F2F7; margin: 0; overflow: hidden;")

    # ── Left drawer (sidebar) ─────────────────────────────────────────────────
    with ui.left_drawer(value=True, fixed=True).style(
        "width: 272px; padding: 16px 14px;"
        "display: flex; flex-direction: column; overflow-y: auto;"
    ):
        render_sidebar(state, on_new_chat=_handle_new_chat, on_load_session=_handle_load_session)

    # ── Main content area (chat + API panel row) ──────────────────────────────
    # NOTE: Use ui.element("div") — NOT ui.row()/ui.column() — to avoid Quasar
    # injecting flex-wrap:wrap which breaks our side-by-side flex layout.
    with ui.element("div").style(
        "height: 100vh; width: 100%; display: flex; flex-direction: row;"
        "flex-wrap: nowrap; gap: 0; overflow: hidden;"
    ):
        # ── Chat column ───────────────────────────────────────────────────────
        with ui.element("div").style(
            "flex: 1; min-width: 0; height: 100vh; display: flex;"
            "flex-direction: column; padding: 0 28px; position: relative; z-index: 2;"
        ):
            # Scrollable chat area
            with ui.scroll_area().style(
                "flex: 1; min-height: 0; background: transparent;"
            ) as scroll_area:
                state.chat_scroll = scroll_area
                with ui.element("div").style(
                    "width: 100%; display: flex; flex-direction: column;"
                    "gap: 0; padding: 24px 0 16px 0;"
                ) as chat_col:
                    state.chat_column = chat_col

                    state.empty_state = None
                    _render_all_messages()
                    ui.html('<div id="chat-end" style="height:1px;"></div>')

            # ── Floating glass input island ───────────────────────────────────
            with ui.element("div").classes("chat-input-area w-full"):
                with ui.element("div").classes("chat-input-island"):
                    state.input_field = (
                        ui.input(placeholder="Message dagi…")
                        .classes("flex-1 chat-input")
                        .props("borderless dense")
                        .style("min-width: 0;")
                    )
                    state.input_field.on(
                        "keydown.enter.prevent",
                        lambda: asyncio.ensure_future(_handle_send()),
                    )
                    ui.button(
                        "Send  ↑",
                        on_click=lambda: asyncio.ensure_future(_handle_send()),
                    ).classes("send-btn").props("flat dense")

        # ── API Payload Panel ─────────────────────────────────────────────────
        with ui.element("div").style(
            "width: 380px; min-width: 380px; height: 100vh;"
            "border-left: 1px solid rgba(60,60,67,0.09);"
            "background: #F7F7F8; padding: 16px 14px; overflow: hidden;"
            "display: flex; flex-direction: column;"
        ).bind_visibility_from(state, "show_debug") as api_panel_col:
            state.api_panel = api_panel_col
            ui.html('<div class="sidebar-section-label" style="margin-bottom:10px;">API Payload</div>')
            with ui.scroll_area().style("flex: 1; min-height: 0;"):
                state.api_panel_html = ui.html(
                    '<pre class="api-payload-output">— No call yet —</pre>'
                )


# ── Interaction handlers ──────────────────────────────────────────────────────

async def _handle_send() -> None:
    """Called when the user presses Enter in the input field."""
    if not state.input_field:
        return
    task = (state.input_field.value or "").strip()
    if not task or state.agent_running:
        return

    # Clear input immediately
    state.input_field.set_value("")
    state.input_field.disable()
    state.agent_running = True

    if state.stop_btn:
        state.stop_btn.set_visibility(True)

    # Build UI message records
    now = datetime.utcnow().isoformat()
    user_ui_msg = {
        "role": "user",
        "content": task,
        "tool_calls": [],
        "input_tokens": None,
        "output_tokens": None,
        "cost": None,
        "timestamp": now,
        "api_snapshot": None,
        "reasoning": None,
    }
    asst_ui_msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [],
        "input_tokens": None,
        "output_tokens": None,
        "cost": None,
        "timestamp": now,
        "api_snapshot": None,
        "reasoning": None,
    }
    state.messages.append(user_ui_msg)
    state.messages.append(asst_ui_msg)
    state.current_asst_ui_msg = asst_ui_msg

    # Render message bubbles in the chat column
    with state.chat_column:
        render_user_message(task, now)
        asst_view = render_assistant_message_shell(now)
        # Scroll anchor stays at bottom
        ui.run_javascript(
            "var el=document.getElementById('chat-end'); if(el) el.scrollIntoView({behavior:'smooth'});"
        )

    state.current_assistant_view = asst_view

    # Build agent config
    cfg = resolve_model_config(state.selected_model_id or None)
    cfg.thread_id = state.current_thread_id

    callbacks = make_callbacks(state)
    prior_msgs = state.conversation_msgs or None

    def _run_agent() -> None:
        """Runs on a threadpool thread via run.io_bound."""
        loop_obj = AgentLoop(cfg, registry, callbacks, initial_messages=prior_msgs)
        state.system_parts = loop_obj.system_parts
        state.current_thread_id = loop_obj.tracker.thread_id
        try:
            loop_obj.run(task)
        finally:
            state.conversation_msgs = loop_obj._messages

    await run.io_bound(_run_agent)


def _handle_new_chat() -> None:
    """Reset state and clear the chat area."""
    state.messages = []
    state.conversation_msgs = []
    state.system_parts = []
    state.agent_running = False
    state.total_input_tok = 0
    state.total_output_tok = 0
    state.total_cost = 0.0
    state.current_iter = 0
    state.current_thread_id = None
    state.current_assistant_view = None
    state.current_asst_ui_msg = None
    state.stop_event.clear()

    # Reset sidebar widgets
    from archive.nicegui_app.components.sidebar import refresh_sidebar_stats
    refresh_sidebar_stats(state)
    if state.iter_row:
        state.iter_row.set_visibility(False)
    if state.stop_btn:
        state.stop_btn.set_visibility(False)
    if state.export_row:
        state.export_row.set_visibility(False)
    if state.input_field:
        state.input_field.enable()

    # Rebuild chat area
    if state.chat_column:
        state.chat_column.clear()
        with state.chat_column:
            state.empty_state = None
            ui.html('<div id="chat-end" style="height:1px;"></div>')


async def _handle_load_session(sess: dict, thread_id: str) -> None:
    """Load a historical session into the UI for continuation."""
    ok = apply_session_to_state(state, sess, thread_id)
    if not ok:
        ui.notify("This session cannot be continued (old format — no raw_messages).",
                  type="warning", timeout=4000)
        return

    # Rebuild chat area with loaded messages
    if state.chat_column:
        state.chat_column.clear()
        with state.chat_column:
            _render_all_messages()
            ui.html('<div id="chat-end"></div>')
        ui.run_javascript(
            "var el=document.getElementById('chat-end'); if(el) el.scrollIntoView();"
        )

    # Update sidebar stats
    from archive.nicegui_app.components.sidebar import refresh_sidebar_stats
    refresh_sidebar_stats(state)
    if state.export_row:
        state.export_row.set_visibility(True)

    ui.notify("Session loaded. Continue the conversation below.", type="positive", timeout=2500)


def _render_all_messages() -> None:
    """Render all messages currently in state.messages into the current NiceGUI parent."""
    for msg in state.messages:
        role = msg.get("role", "")
        if role == "user":
            render_user_message(msg.get("content") or "", msg.get("timestamp", ""))
        elif role == "assistant":
            render_static_assistant_message(msg)


# ── Entry point ───────────────────────────────────────────────────────────────

def start() -> None:
    ui.run(
        title="dagi",
        favicon="◈",
        port=8080,
        reload=False,
        show=True,
    )


if __name__ in {"__main__", "__mp_main__"}:
    start()
