"""tests/tui/test_sidebar_render.py — verify Sidebar.render() stacks sections vertically."""
from __future__ import annotations

from pathlib import Path

from rich.console import Group

from agent.affect import AffectSnapshot, AffectVector
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


def test_sidebar_renders_textual_affect_and_process_state() -> None:
    sb = _make_sidebar()
    sb.update_affect(AffectSnapshot(
        baseline=AffectVector(0.0, 0.0, 0.0),
        current=AffectVector(0.25, -0.50, 0.75),
        emote_id="focused",
        asset=TextFallback(Path("default.md"), "test", "DAGI"),
        reason="adjust",
    ))
    sb.update_process_state(ProcessSnapshot(
        state="tool:read",
        asset=TextFallback(Path("default.md"), "test", "DAGI"),
    ))

    assert sb._emote_name == "focused"
    assert "V=+0.25 A=-0.50 D=+0.75" in sb._emote_display
    assert "process=tool:read" in sb._emote_display
