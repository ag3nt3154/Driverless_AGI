from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING, Callable

from agent.loop import AgentCallbacks

from .conversation import ConversationPane
from .sidebar import Sidebar
from .streaming import StreamPreview
from .utils import _breakdown
from .notifications import notify

if TYPE_CHECKING:
    from .app import DagiApp


def build_callbacks(app: DagiApp, loop_ref: list) -> AgentCallbacks:
    """Build AgentCallbacks wired to the live TUI widgets."""
    sidebar = app.query_one(Sidebar)
    conv = app.query_one(ConversationPane)
    preview = app.query_one(StreamPreview)
    stats = app._stats
    verbose = app._verbose

    def on_tool_start(name, _desc, args):
        app.call_from_thread(conv.append_tool_start, name, args, verbose)

    def on_tool_end(name, result):
        stats.record_tool(name)
        app.call_from_thread(conv.append_tool_end, name, result, verbose)

    def on_assistant_text(text):
        if text.strip():
            app.call_from_thread(conv.append_assistant, text)

    def on_token_update(inp, out, cost, thinking=0):
        stats.update_tokens(inp, out, cost, thinking)
        app.call_from_thread(
            sidebar.update_stats, stats.input_tok, stats.output_tok, stats.cost, stats.thinking_tok
        )

    def on_reasoning(text):
        if text.strip():
            app.call_from_thread(conv.append_reasoning, text)

    # ── Streaming preview ────────────────────────────────────────────────
    # State lives here (agent-thread-only access: start → deltas → end are
    # all fired from the agent worker thread, never concurrently).
    # call_from_thread is throttled to ≥50 ms *per delta kind* between UI
    # refreshes so fast token streams don't stall the agent thread; every
    # flush passes the FULL accumulated strings, so skipped refreshes lose
    # nothing. Throttling is tracked separately for "text" and "reasoning"
    # so that the first delta of a kind (e.g. reasoning starting right after
    # text) always renders immediately instead of being swallowed by a
    # throttle window opened by an unrelated kind moments earlier.
    _stream = {
        "reasoning": "", "text": "",
        "last_flush": {"reasoning": 0.0, "text": 0.0},
        "expanded": False,
    }
    _FLUSH_INTERVAL = 0.05

    def _flush_stream(kind: str = "text", force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - _stream["last_flush"][kind]) < _FLUSH_INTERVAL:
            return
        _stream["last_flush"][kind] = now
        app.call_from_thread(preview.show_progress, _stream["reasoning"], _stream["text"])
        if not _stream["expanded"]:
            _stream["expanded"] = True
            app.call_from_thread(app._expand_stream_preview)

    def on_stream_start() -> None:
        _stream["reasoning"] = ""
        _stream["text"] = ""
        _stream["last_flush"] = {"reasoning": 0.0, "text": 0.0}
        _stream["expanded"] = False

    def on_assistant_text_delta(chunk: str) -> None:
        _stream["text"] += chunk
        _flush_stream(kind="text")

    def on_reasoning_delta(chunk: str) -> None:
        _stream["reasoning"] += chunk
        _flush_stream(kind="reasoning")

    def on_stream_end() -> None:
        if _stream["reasoning"] or _stream["text"]:
            _flush_stream(force=True)   # final render with the complete text
        app.call_from_thread(preview.finish)
        if _stream["expanded"]:
            app.call_from_thread(app._collapse_stream_preview)

    def on_compaction(kept, removed):
        app.call_from_thread(conv.append_info,
            f"[yellow]⚡ Context compacted — removed {removed} messages, kept {kept}[/yellow]")
        if loop_ref:
            app.call_from_thread(sidebar.update_context, _breakdown(loop_ref[0]._messages))

    def on_model_switch(from_name, to_name):
        app.call_from_thread(conv.append_info,
            f"[bold cyan]⇄ Model switch:[/bold cyan] [dim]{from_name}[/dim] → [bold]{to_name}[/bold]")
        app.call_from_thread(sidebar.update_model, to_name)

    def on_error(exc):
        app.call_from_thread(conv.append_error, str(exc))

    def on_pause():
        app.call_from_thread(sidebar.set_status, "paused")
        app.call_from_thread(conv.append_info,
            "[yellow]⏸ Server error — session paused. "
            "Send a message to retry when the server is back.[/yellow]")
        app.call_from_thread(app._enable_input)

    def on_api_call(messages):
        app.call_from_thread(sidebar.update_context, _breakdown(messages))

    def on_ask_user(question, options, timeout):
        notify("DAGI has a question", question)
        evt = threading.Event()
        container: list = []
        app.call_from_thread(app._show_ask_user, question, options, timeout, evt, container)
        safety = (timeout + 60) if timeout is not None else 600
        evt.wait(timeout=safety)
        if container:
            return container[0]
        return next((o["label"] for o in options if o.get("recommended")),
                    options[0]["label"] if options else "")

    def on_plan_shown():
        notify("DAGI's plan is ready", "Review the plan and reply with any changes.")

    def on_continue_injected(cur: int, mx: int) -> None:
        app.call_from_thread(
            conv.append_info,
            f"[dim yellow]↩ No exit flag — continue prompt injected ({cur}/{mx})[/dim yellow]",
        )

    def on_emote(emote: str) -> None:
        app.call_from_thread(sidebar.update_emote, emote)

    def on_subagent_event_factory(subagent_type: str) -> Callable[[str], None]:
        return build_subagent_relay_callback(app, subagent_type)

    def on_done(result: str) -> None:
        # notify() is silently skipped whenever the console window has OS focus
        # (see notifications.py), and a turn can legitimately end with empty
        # text (e.g. right after a subagent handoff). Without this line, that
        # combination leaves zero visible signal that the turn finished —
        # indistinguishable from a hang.
        app.call_from_thread(
            conv.append_info, "[dim]— turn complete —[/dim]"
        )
        notify("DAGI is done", result or "Response complete.")

    return AgentCallbacks(
        on_tool_start=on_tool_start, on_tool_end=on_tool_end,
        on_assistant_text=on_assistant_text, on_token_update=on_token_update,
        on_iteration=lambda _: None, on_done=on_done, on_error=on_error,
        on_api_call=on_api_call, on_reasoning=on_reasoning,
        on_compaction=on_compaction, on_model_switch=on_model_switch,
        on_ask_user=on_ask_user, on_emote=on_emote,
        on_subagent_event_factory=on_subagent_event_factory,
        on_pause=on_pause, supports_pause=True,
        on_continue_injected=on_continue_injected,
        on_plan_shown=on_plan_shown,
        on_stream_start=on_stream_start, on_stream_end=on_stream_end,
        on_assistant_text_delta=on_assistant_text_delta,
        on_reasoning_delta=on_reasoning_delta,
    )


def build_subagent_relay_callback(
    app: "DagiApp", subagent_type: str
) -> Callable[[str], None]:
    """Return a callback that relays subagent stdout JSON events to the TUI."""
    conv = app.query_one(ConversationPane)
    label = f"[bold cyan][{subagent_type}][/bold cyan]"

    def on_event(line: str) -> None:
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            app.call_from_thread(conv.append_info, f"[dim]{line}[/dim]")
            return

        t = evt.get("type", "")
        if t == "start":
            app.call_from_thread(
                conv.append_info,
                f"[bold cyan]┌─ subagent: {subagent_type} ────────────────────────┐[/bold cyan]",
            )
        elif t == "tool_call":
            name = evt.get("name", "?")
            args = evt.get("args", "")
            app.call_from_thread(
                conv.append_info,
                f"  {label} [dim cyan]▶ {name}[/dim cyan] [dim]{args[:80]}[/dim]",
            )
        elif t == "tool_result":
            name = evt.get("name", "?")
            chars = evt.get("chars", 0)
            app.call_from_thread(
                conv.append_info,
                f"  {label} [dim green]✓ {name} ({chars} chars)[/dim green]",
            )
        elif t == "message":
            content = evt.get("content", "")
            if content.strip():
                app.call_from_thread(
                    conv.append_info,
                    f"  {label} [#cccccc]{content}[/#cccccc]",
                )
        elif t == "status":
            text = evt.get("text", "")
            app.call_from_thread(
                conv.append_info,
                f"  {label} [dim yellow]{text}[/dim yellow]",
            )
        elif t == "error":
            msg = evt.get("message", "")
            app.call_from_thread(
                conv.append_info,
                f"  {label} [bold red]error: {msg}[/bold red]",
            )
        elif t == "done":
            app.call_from_thread(
                conv.append_info,
                f"[bold cyan]└─ subagent: {subagent_type} done ─────────────────────┘[/bold cyan]",
            )

    return on_event
