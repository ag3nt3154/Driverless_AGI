from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from nicegui import ui

from agent.config_loader import (
    load_raw_config,
    list_model_ids,
    resolve_model_config,
    save_config,
)

if TYPE_CHECKING:
    from nicegui_app.state import AppState


def render_sidebar(state: "AppState", on_new_chat: Callable, on_load_session: Callable) -> None:
    """
    Render the full left drawer contents.

    on_new_chat()                     — callback for the New Chat button
    on_load_session(sess, thread_id)  — callback for a session history button
    """
    # ── Top row: New Chat + Settings ─────────────────────────────────────────
    with ui.row().classes("w-full items-center").style("gap: 8px; margin-bottom: 4px;"):
        ui.button("＋ New Chat", on_click=on_new_chat).classes("flex-1 sidebar-btn").props("flat")
        _render_settings_popover(state)

    ui.separator()

    # ── Current session stats ─────────────────────────────────────────────────
    ui.html('<div class="sidebar-section-label">Current Session</div>')

    # Token / cost stat box
    state.tok_label = ui.html(_stat_box_html(state.total_input_tok, state.total_output_tok, state.total_cost))

    # Iteration progress (hidden when no run is active)
    with ui.column().classes("w-full").style("gap:4px; margin-top:4px;") as iter_row:
        iter_row.set_visibility(False)
        state.iter_label = ui.html('<div class="stat-label">Iteration 0 / 20</div>')
        state.iter_bar = (
            ui.linear_progress(value=0.0, size="6px")
            .classes("iter-progress w-full")
        )
    state.iter_row = iter_row

    # Stop button
    state.stop_btn = (
        ui.button("■ Stop", on_click=lambda: _handle_stop(state))
        .classes("w-full stop-btn")
        .props("flat")
    )
    state.stop_btn.set_visibility(False)

    # Export button row
    with ui.row().classes("w-full").style("margin-top:4px;") as export_row:
        export_row.set_visibility(bool(state.messages))
        ui.button(
            "⬇ Export session",
            on_click=lambda: _export_session(state),
        ).classes("w-full export-btn").props("flat")
    state.export_row = export_row

    ui.separator()

    # ── Past sessions ─────────────────────────────────────────────────────────
    ui.html('<div class="sidebar-section-label">Past Sessions</div>')

    with ui.scroll_area().style("height: calc(100vh - 380px); padding-right: 4px;"):
        with ui.column().classes("w-full").style("gap: 4px;") as history_col:
            state.history_column = history_col
            _render_history_buttons(state, on_load_session)


def refresh_sidebar_stats(state: "AppState") -> None:
    """Update token/cost labels in place. Called from callbacks via call_soon_threadsafe."""
    if state.tok_label:
        state.tok_label.set_content(
            _stat_box_html(state.total_input_tok, state.total_output_tok, state.total_cost)
        )


def refresh_iteration(state: "AppState") -> None:
    """Update iteration bar and label. Called from on_iteration callback."""
    if state.iter_row:
        state.iter_row.set_visibility(True)
    if state.iter_label:
        state.iter_label.set_content(
            f'<div class="stat-label">Iteration {state.current_iter} / {state.max_iter}</div>'
        )
    if state.iter_bar:
        frac = state.current_iter / max(state.max_iter, 1)
        state.iter_bar.set_value(frac)


def refresh_history(state: "AppState", on_load_session: Callable) -> None:
    """Rebuild the past sessions button list after a run completes."""
    if not state.history_column:
        return
    state.history_column.clear()
    with state.history_column:
        _render_history_buttons(state, on_load_session)


def _render_history_buttons(state: "AppState", on_load_session: Callable) -> None:
    sessions = state.history_sessions[:20]
    if not sessions:
        ui.html('<div style="font-size:0.75rem; color:rgba(100,116,139,0.55); padding:8px 2px; font-family:\'Plus Jakarta Sans\',sans-serif;">No past sessions yet.</div>')
        return
    for thread in sessions:
        tid = thread["thread_id"]
        title = thread["title"] or tid[:12]
        latest = thread["sessions"][-1]
        has_raw = latest.get("has_raw", False)
        btn = (
            ui.button(title, on_click=lambda t=latest, i=tid: on_load_session(t, i))
            .classes("w-full history-session-btn")
            .props("flat align=left")
            .style("font-size:0.76rem; text-align:left; margin-bottom:2px;")
        )
        if not has_raw:
            btn.disable()
            btn.tooltip("Old format — cannot continue")


def _render_settings_popover(state: "AppState") -> None:
    with ui.button("⚙", on_click=None).classes("sidebar-btn").props("flat round").style("min-width:36px; font-size:1rem;"):
        with ui.menu().props("auto-close"):
            with ui.card().style("padding: 18px; min-width: 280px;"):
                ui.html('<div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:0.15em; color:rgba(148,163,184,0.6); font-weight:600; margin-bottom:14px; font-family:\'Plus Jakarta Sans\',sans-serif;">Settings</div>')

                raw_cfg = load_raw_config()
                catalog = raw_cfg.get("models", {})
                model_ids = list_model_ids()
                current_id = raw_cfg.get("default_model", model_ids[0] if model_ids else "")
                if not state.selected_model_id:
                    state.selected_model_id = current_id

                model_select = (
                    ui.select(
                        options={mid: catalog[mid].get("name", mid) for mid in model_ids},
                        value=state.selected_model_id,
                        label="Model",
                    )
                    .classes("w-full")
                    .bind_value(state, "selected_model_id")
                )

                cfg = resolve_model_config()
                max_iter_input = (
                    ui.number(
                        label="Max iterations",
                        value=cfg.max_iterations,
                        min=1,
                        max=200,
                        step=1,
                    )
                    .classes("w-full")
                    .style("margin-top: 8px;")
                )

                def _on_debug_change(e):
                    handler = getattr(state, "_on_debug_toggle", None)
                    if handler:
                        handler(e.value)

                debug_toggle = (
                    ui.switch("Debug: show API payload", value=state.show_debug)
                    .style("margin-top: 8px;")
                    .bind_value(state, "show_debug")
                    .on("update:modelValue", _on_debug_change)
                )

                def save_settings():
                    new_max = int(max_iter_input.value or 20)
                    save_config(
                        default_model=state.selected_model_id,
                        max_iterations=new_max,
                    )
                    state.max_iter = new_max
                    ui.notify("Settings saved.", type="positive", timeout=2000)

                ui.button("Save", on_click=save_settings).classes("w-full").style("margin-top: 12px;")


def _stat_box_html(in_tok: int, out_tok: int, cost: float) -> str:
    return (
        f'<div class="stat-box">'
        f'  <div class="stat-box-inner">'
        f'    <div>'
        f'      <div class="stat-label">Tokens</div>'
        f'      <div class="stat-val">↑ {in_tok:,} &nbsp; ↓ {out_tok:,}</div>'
        f'    </div>'
        f'    <div class="stat-divider"></div>'
        f'    <div>'
        f'      <div class="stat-label">Cost</div>'
        f'      <div class="stat-val">${cost:.5f}</div>'
        f'    </div>'
        f'  </div>'
        f'</div>'
    )


def _handle_stop(state: "AppState") -> None:
    state.stop_event.set()
    state.agent_running = False
    state.stop_btn.set_visibility(False)
    state.iter_row.set_visibility(False)
    if state.input_field:
        state.input_field.enable()
    # Append stop note to current assistant bubble content
    if state.current_assistant_view:
        view = state.current_assistant_view
        current = view.content_html.content or ""
        view.content_html.set_content(current + "<p><em>[Stopped by user]</em></p>")


def _export_session(state: "AppState") -> None:
    in_tok = state.total_input_tok
    out_tok = state.total_output_tok
    cost = state.total_cost
    data = json.dumps(
        {
            "messages": state.messages,
            "meta": {
                "total_input_tokens": in_tok,
                "total_output_tokens": out_tok,
                "total_cost": cost,
            },
        },
        indent=2,
    )
    fname = f"dagi_session_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    ui.download(data.encode(), fname)
