from __future__ import annotations

import markdown as md_lib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from nicegui import ui

from .tool_card import ToolCardView, render_tool_card, update_tool_card


@dataclass
class AssistantMessageView:
    """
    Holds NiceGUI element references for a live assistant message.
    Callbacks use these to push updates directly into the DOM.
    """
    content_html: Any           # ui.html — the rendered markdown content
    tool_card_container: Any    # ui.column — tool cards appended here
    meta_label: Any             # ui.html — token/cost footer
    reasoning_expansion: Any    # ui.expansion or None
    tool_cards: list = field(default_factory=list)  # list[ToolCardView]


def _escape_html(text: str) -> str:
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _ts_str(iso: str) -> str:
    return iso[:16].replace("T", " ") if iso else ""


def render_user_message(content: str, timestamp: str) -> None:
    """Render a user message bubble (no return — purely side-effectful DOM write)."""
    escaped = _escape_html(content)
    ts = _ts_str(timestamp)
    ui.html(
        f'<div class="user-bubble-shell">'
        f'  <div class="user-bubble">{escaped}</div>'
        f'</div>'
        f'<div class="msg-meta" style="text-align:right">{ts}</div>'
    )


def render_assistant_message_shell(timestamp: str = "") -> AssistantMessageView:
    """
    Render an empty assistant bubble and return a view object with element refs.
    The callbacks will update these refs as the agent produces output.
    """
    ts = _ts_str(timestamp or datetime.utcnow().isoformat())

    with ui.element("div").classes("assistant-bubble-shell"):
        with ui.element("div").classes("assistant-bubble"):
            # Reasoning expander (hidden until reasoning arrives)
            with ui.expansion("🧠  Model Reasoning").classes("reasoning-card w-full") as reasoning_exp:
                reasoning_exp.set_visibility(False)
                reasoning_content = ui.html("")

            # Markdown content area (updated by on_assistant_text)
            content_html = ui.html("").classes("w-full")

            # Tool card container (cards appended here as tools fire)
            tool_card_container = ui.column().classes("w-full").style("gap: 0;")

            # Token / cost footer
            meta_label = ui.html(
                f'<div class="msg-meta">{ts}</div>'
            )

    view = AssistantMessageView(
        content_html=content_html,
        tool_card_container=tool_card_container,
        meta_label=meta_label,
        reasoning_expansion=reasoning_exp,
        tool_cards=[],
    )
    # Store reasoning content ref on the view for callbacks
    view._reasoning_content = reasoning_content  # type: ignore[attr-defined]
    return view


def update_assistant_content(view: AssistantMessageView, text: str) -> None:
    """Called from on_assistant_text callback — renders markdown into the bubble."""
    html = md_lib.markdown(text, extensions=["fenced_code", "tables"]) if text else ""
    view.content_html.set_content(html)


def update_meta_label(view: AssistantMessageView, ts: str,
                       input_tok: int | None, output_tok: int | None,
                       cost: float | None) -> None:
    """Update the token/cost footer on the assistant bubble."""
    tok_info = ""
    if input_tok or output_tok:
        tok_info = f" · {input_tok or 0}↑ {output_tok or 0}↓"
    if cost:
        tok_info += f" · ${cost:.5f}"
    view.meta_label.set_content(
        f'<div class="msg-meta">{_ts_str(ts)}{tok_info}</div>'
    )


def update_reasoning(view: AssistantMessageView, text: str) -> None:
    """Show the reasoning expansion and update its content."""
    if not text:
        return
    html = md_lib.markdown(text, extensions=["fenced_code", "tables"])
    view._reasoning_content.set_content(html)  # type: ignore[attr-defined]
    view.reasoning_expansion.set_visibility(True)


def render_static_assistant_message(msg: dict) -> None:
    """
    Render a fully-complete historical assistant message (from a loaded session).
    Unlike render_assistant_message_shell, this takes a complete message dict.
    """
    tool_calls = msg.get("tool_calls", [])
    content = msg.get("content") or ""
    ts = _ts_str(msg.get("timestamp", ""))
    reasoning = msg.get("reasoning")
    input_tok = msg.get("input_tokens")
    output_tok = msg.get("output_tokens")
    cost = msg.get("cost")

    with ui.element("div").classes("assistant-bubble-shell"):
        with ui.element("div").classes("assistant-bubble"):
            # Reasoning
            if reasoning:
                with ui.expansion("🧠  Model Reasoning").classes("reasoning-card w-full"):
                    html = md_lib.markdown(reasoning, extensions=["fenced_code", "tables"])
                    ui.html(html)

            # Content
            content_html = md_lib.markdown(content, extensions=["fenced_code", "tables"]) if content else ""
            ui.html(content_html).classes("w-full")

            # Tool calls (all done)
            for tc in tool_calls:
                with ui.element("div").classes("tool-card"):
                    with ui.expansion(f"✓  {_tool_summary_static(tc)}", value=False).classes("w-full"):
                        try:
                            args_pretty = __import__("json").dumps(
                                __import__("json").loads(tc["input"]), indent=2
                            )
                        except Exception:
                            args_pretty = tc.get("input", "")
                        ui.html(
                            f'<pre class="tool-output" style="margin:0">{_escape_html(args_pretty)}</pre>'
                        )
                        if tc.get("result"):
                            from .tool_card import _render_tool_output
                            _render_tool_output(tc, tc["result"])

            # Meta
            tok_info = ""
            if input_tok or output_tok:
                tok_info = f" · {input_tok or 0}↑ {output_tok or 0}↓"
            if cost:
                tok_info += f" · ${cost:.5f}"
            ui.html(f'<div class="msg-meta">{ts}{tok_info}</div>')


def _tool_summary_static(tc: dict) -> str:
    """Build tool summary for static (historical) rendering."""
    import json as _json
    name = tc.get("name", "")
    try:
        args = _json.loads(tc.get("input", "{}"))
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
