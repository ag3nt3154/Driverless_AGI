"""
nicegui_app/callbacks.py
────────────────────────
Builds AgentCallbacks that bridge the synchronous agent thread to NiceGUI's
asyncio event loop via loop.call_soon_threadsafe.

Rule: every _update closure must be a plain `def`, never `async def`.
      Coroutines passed to call_soon_threadsafe are created but never awaited.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agent.loop import AgentCallbacks
from archive.nicegui_app.components.chat_message import (
    update_assistant_content,
    update_meta_label,
    update_reasoning,
)
from archive.nicegui_app.components.sidebar import refresh_iteration, refresh_sidebar_stats
from archive.nicegui_app.components.tool_card import render_tool_card, update_tool_card

if TYPE_CHECKING:
    from archive.nicegui_app.state import AppState


def make_callbacks(state: "AppState") -> AgentCallbacks:
    """
    Return an AgentCallbacks instance wired to update the live NiceGUI UI.
    All DOM mutations are posted to the event loop via call_soon_threadsafe.
    """
    loop = state._loop  # captured once; never None at call time

    def _schedule(fn):
        """Post fn (a plain callable) onto the event loop. Thread-safe."""
        loop.call_soon_threadsafe(fn)

    # ── on_tool_start ─────────────────────────────────────────────────────────
    def on_tool_start(name: str, description: str, args: str) -> None:
        def _update():
            view = state.current_assistant_view
            if view is None:
                return
            tc_data = {
                "name": name,
                "description": description,
                "input": args,
                "result": "",
                "status": "running",
            }
            # Ensure the UI messages list also gets this tool call
            if state.current_asst_ui_msg is not None:
                state.current_asst_ui_msg.setdefault("tool_calls", []).append(tc_data)
            # Render the card inside the tool_card_container
            with view.tool_card_container:
                card_view = render_tool_card(tc_data)
            view.tool_cards.append(card_view)
            _scroll_to_bottom(state)
        _schedule(_update)

    # ── on_tool_end ───────────────────────────────────────────────────────────
    def on_tool_end(name: str, result: str) -> None:
        def _update():
            view = state.current_assistant_view
            if view is None or not view.tool_cards:
                return
            last_card = view.tool_cards[-1]
            update_tool_card(last_card, result, "done")
            _scroll_to_bottom(state)
        _schedule(_update)

    # ── on_assistant_text ─────────────────────────────────────────────────────
    def on_assistant_text(text: str) -> None:
        def _update():
            view = state.current_assistant_view
            if view is None:
                return
            if state.current_asst_ui_msg is not None:
                state.current_asst_ui_msg["content"] = text
            update_assistant_content(view, text)
            _scroll_to_bottom(state)
        _schedule(_update)

    # ── on_token_update ───────────────────────────────────────────────────────
    def on_token_update(input_tokens: int, output_tokens: int, cost: float | None) -> None:
        def _update():
            state.total_input_tok += input_tokens or 0
            state.total_output_tok += output_tokens or 0
            if cost:
                state.total_cost += cost
            if state.current_asst_ui_msg is not None:
                state.current_asst_ui_msg["input_tokens"] = input_tokens
                state.current_asst_ui_msg["output_tokens"] = output_tokens
                state.current_asst_ui_msg["cost"] = cost
            # Update sidebar stats
            refresh_sidebar_stats(state)
            # Update meta label on assistant bubble
            view = state.current_assistant_view
            if view is not None and state.current_asst_ui_msg is not None:
                msg = state.current_asst_ui_msg
                update_meta_label(
                    view,
                    msg.get("timestamp", ""),
                    input_tokens,
                    output_tokens,
                    cost,
                )
        _schedule(_update)

    # ── on_iteration ──────────────────────────────────────────────────────────
    def on_iteration(current: int, maximum: int) -> None:
        def _update():
            state.current_iter = current
            state.max_iter = maximum
            refresh_iteration(state)
        _schedule(_update)

    # ── on_done ───────────────────────────────────────────────────────────────
    def on_done(result: str) -> None:
        def _update():
            state.agent_running = False
            state.current_iter = 0
            if state.iter_row:
                state.iter_row.set_visibility(False)
            if state.stop_btn:
                state.stop_btn.set_visibility(False)
            if state.input_field:
                state.input_field.enable()
            if state.export_row:
                state.export_row.set_visibility(True)
            # Reload session history to include the newly saved session
            from archive.nicegui_app.history import load_history_sessions
            from nicegui.background_tasks import create as _create_bg
            # Kick off async reload; history refresh needs io_bound
            import asyncio
            asyncio.ensure_future(_reload_history_async(state))
        _schedule(_update)

    # ── on_error ──────────────────────────────────────────────────────────────
    def on_error(error: Exception) -> None:
        def _update():
            state.agent_running = False
            state.current_iter = 0
            if state.iter_row:
                state.iter_row.set_visibility(False)
            if state.stop_btn:
                state.stop_btn.set_visibility(False)
            if state.input_field:
                state.input_field.enable()
            view = state.current_assistant_view
            if view is not None:
                update_assistant_content(view, f"⚠ Error: {error}")
        _schedule(_update)

    # ── on_api_call ───────────────────────────────────────────────────────────
    def on_api_call(messages: list) -> None:
        def _update():
            if state.current_asst_ui_msg is not None:
                state.current_asst_ui_msg["api_snapshot"] = messages
            if state.show_debug and state.api_panel_html:
                import json as _json
                state.api_panel_html.set_content(
                    f'<pre class="api-payload-output">{_json.dumps(messages, indent=2, default=str)}</pre>'
                )
        _schedule(_update)

    # ── on_reasoning ──────────────────────────────────────────────────────────
    def on_reasoning(text: str) -> None:
        def _update():
            if state.current_asst_ui_msg is not None:
                state.current_asst_ui_msg["reasoning"] = text
            view = state.current_assistant_view
            if view is not None:
                update_reasoning(view, text)
        _schedule(_update)

    # ── on_compaction ─────────────────────────────────────────────────────────
    def on_compaction(messages_kept: int, messages_removed: int) -> None:
        def _update():
            if state.chat_column is None:
                return
            from nicegui import ui
            with state.chat_column:
                ui.html(
                    f'<div style="text-align:center;font-size:0.72rem;'
                    f'color:rgba(100,116,139,0.55);padding:6px 0;'
                    f'border-top:1px dashed rgba(100,116,139,0.2);'
                    f'border-bottom:1px dashed rgba(100,116,139,0.2);margin:4px 0;">'
                    f'Context compacted — {messages_removed} messages summarized, '
                    f'{messages_kept} kept'
                    f'</div>'
                )
            _scroll_to_bottom(state)
        _schedule(_update)

    return AgentCallbacks(
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
        on_assistant_text=on_assistant_text,
        on_token_update=on_token_update,
        on_iteration=on_iteration,
        on_done=on_done,
        on_error=on_error,
        on_api_call=on_api_call,
        on_reasoning=on_reasoning,
        on_compaction=on_compaction,
    )


async def _reload_history_async(state: "AppState") -> None:
    """Async wrapper to reload history without blocking the event loop."""
    from nicegui import run
    from archive.nicegui_app.history import load_history_sessions

    # Import here to avoid circular import at module load time
    sessions = await run.io_bound(load_history_sessions)
    state.history_sessions = sessions

    # Re-render history buttons if we have a reference
    # The on_load_session callback is held in main.py; we trigger a UI rebuild
    # by clearing and repopulating the history column
    if state.history_column:
        state.history_column.clear()
        with state.history_column:
            from archive.nicegui_app.components.sidebar import _render_history_buttons
            _render_history_buttons(state, state._on_load_session)  # type: ignore[attr-defined]


def _scroll_to_bottom(state: "AppState") -> None:
    """Scroll the chat area to the latest message."""
    from nicegui import ui
    ui.run_javascript(
        "var el = document.getElementById('chat-end'); if(el) el.scrollIntoView({behavior:'smooth'});"
    )
