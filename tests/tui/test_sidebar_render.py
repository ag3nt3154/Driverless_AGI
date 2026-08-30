"""tests/tui/test_sidebar_render.py — verify Sidebar.render() stacks sections vertically."""
from __future__ import annotations

from pathlib import Path

from rich.console import Group

from agent.expression import ExpressionSnapshot
from agent.expression_assets import TextFallback
from agent.process_state import ProcessSnapshot
from tui.sidebar import Sidebar


def _make_sidebar() -> Sidebar:
    return Sidebar(
        model_name="test-model",
        context_window=80_000,
        reserve_tokens=4_096,
        dagi_root=Path("."),
        project_path=Path("."),
        memory_root=None,
    )


def test_render_returns_group() -> None:
    sb = _make_sidebar()
    result = sb.render()
    assert isinstance(result, Group), f"Expected Group, got {type(result)}"


def test_render_group_has_three_children() -> None:
    sb = _make_sidebar()
    result = sb.render()
    # Group is a NamedTuple; renderables is a tuple of its children
    # Structure: _status_col, Text(""), _tokens_context_col, Text(""), _plan_col
    assert len(result.renderables) == 5


def test_sidebar_expression_does_not_replace_process_state() -> None:
    sb = _make_sidebar()
    sb.update_expression(ExpressionSnapshot(
        emote_id="focused",
        asset=TextFallback(Path("default.md"), "test", "DAGI"),
    ))
    sb.update_process_state(ProcessSnapshot(
        state="tool:read",
        asset=TextFallback(Path("default.md"), "test", "DAGI"),
    ))

    assert sb._emote_name == ""
    assert sb._emote_display == "process=tool:read"


def test_sidebar_renders_process_state_as_plain_text() -> None:
    sb = _make_sidebar()
    sb.update_process_state(ProcessSnapshot(
        state="tool:[/red]",
        asset=TextFallback(Path("default.md"), "test", "DAGI"),
    ))

    status_group = sb.render().renderables[0]
    face_group = status_group.renderables[0]
    (face_text,) = face_group.renderables

    assert face_text.plain.endswith("process=tool:[/red]")
