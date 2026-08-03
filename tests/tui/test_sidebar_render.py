"""tests/tui/test_sidebar_render.py — verify Sidebar.render() stacks sections vertically."""
from __future__ import annotations

from pathlib import Path

from rich.console import Group

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
    assert len(result.renderables) == 3
