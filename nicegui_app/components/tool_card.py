from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from typing import Any

from nicegui import ui


def _tool_summary(tc: dict) -> str:
    """Build a short one-line label for the tool call expansion header."""
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


@dataclass
class ToolCardView:
    expansion: Any          # ui.expansion — the collapsible card
    status_label: Any       # ui.label — "⟳" or "✓"
    output_container: Any   # ui.element — filled in on tool_end
    tc_data: dict           # reference to the mutable tool call dict


def render_tool_card(tc_data: dict) -> ToolCardView:
    """
    Create a tool card inside the current NiceGUI parent context.
    Returns a view object so callbacks can update it later.
    """
    label = _tool_summary(tc_data)
    is_running = tc_data.get("status") == "running"

    card_classes = "tool-card tool-card-running" if is_running else "tool-card"

    with ui.element("div").classes(card_classes) as card_el:
        with ui.expansion(f"⟳  {label}" if is_running else f"✓  {label}",
                          value=is_running) as expansion:
            expansion.classes("w-full")

            # Input JSON block
            try:
                args_pretty = json.dumps(json.loads(tc_data["input"]), indent=2)
            except Exception:
                args_pretty = tc_data["input"]

            ui.html(f'<pre class="tool-output" style="margin:0">{_escape(args_pretty)}</pre>')

            # Output container (empty until tool_end)
            output_container = ui.column().classes("w-full").style("gap:0; margin-top:4px;")

    # The status label is embedded in the expansion header — we track card_el for class mutation
    view = ToolCardView(
        expansion=expansion,
        status_label=card_el,   # we toggle card classes on card_el
        output_container=output_container,
        tc_data=tc_data,
    )
    return view


def update_tool_card(view: ToolCardView, result: str, status: str) -> None:
    """
    Called from on_tool_end via call_soon_threadsafe.
    Updates the card: sets ✓, collapses it, fills the output container.
    """
    tc = view.tc_data
    tc["result"] = result
    tc["status"] = status

    label = _tool_summary(tc)
    view.expansion.set_text(f"✓  {label}")
    view.expansion.set_value(False)   # collapse on completion
    view.status_label.classes(remove="tool-card-running")

    # Fill output
    view.output_container.clear()
    with view.output_container:
        _render_tool_output(tc, result)


def _render_tool_output(tc: dict, result: str) -> None:
    """Render appropriate output widget inside output_container."""
    if not result:
        return

    if result.startswith("__list__:"):
        try:
            data = json.loads(result[len("__list__:"):])
            imgs = data if isinstance(data, list) else [data]
            for img in imgs:
                ui.image(img).style("max-width:100%; border-radius:8px; margin-top:4px;")
        except Exception:
            ui.html(f'<pre class="tool-output">{_escape(result[:2000])}</pre>')
    elif tc.get("name") == "edit":
        try:
            args = json.loads(tc["input"])
            old = args.get("old_string", args.get("oldText", ""))
            new = args.get("new_string", args.get("newText", ""))
            diff = "\n".join(difflib.unified_diff(
                old.splitlines(), new.splitlines(),
                fromfile="before", tofile="after", lineterm=""
            ))
            _code_block(diff or result[:2000], lang="diff")
        except Exception:
            _code_block(result[:2000], lang="bash")
    else:
        _code_block(result[:3000], lang="bash")


def _code_block(text: str, lang: str = "bash") -> None:
    """Render a pre block styled as a code output."""
    ui.html(f'<pre class="tool-output">{_escape(text)}</pre>')


def _escape(text: str) -> str:
    """Minimal HTML escaping for pre-formatted output."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
