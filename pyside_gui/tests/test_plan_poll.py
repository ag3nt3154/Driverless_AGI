from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pyside_gui  # noqa: F401 — must be imported before any PySide6 import

from tools._plan_parser import parse_subtask_statuses


def _make_window(
    plan_path: str | None = None, *, bound: bool = True
):
    """Build a __new__-only DagiMainWindow with fakes for _poll_plan.

    _poll_plan touches only _current_loop_ref and the sidebar it routes to,
    so no QApplication or real widgets are needed (mirrors test_bridge.py).
    """
    from pyside_gui.app import DagiMainWindow

    window = DagiMainWindow.__new__(DagiMainWindow)
    window._left_sidebar = MagicMock()
    window._current_loop_ref = (
        [SimpleNamespace(config=SimpleNamespace(active_plan_file=plan_path))]
        if bound
        else []
    )
    return window


def test_poll_plan_pushes_parsed_plan_to_left_sidebar(tmp_path):
    """A bound loop with an active plan file feeds the left-sidebar plan view."""
    plan = tmp_path / "plan.md"
    plan_text = (
        "# Plan — Test Title\n\n"
        "## Subtasks\n\n"
        "### Subtask 1: [x] done thing\n"
        "### Subtask 2: [ ] todo thing\n"
    )
    plan.write_text(plan_text, encoding="utf-8")

    window = _make_window(str(plan))
    window._poll_plan()

    expected = parse_subtask_statuses(plan_text)
    window._left_sidebar.update_plan.assert_called_once_with(
        expected, "Test Title"
    )


def test_poll_plan_clears_left_sidebar_when_loop_has_no_plan():
    """A bound loop without an active plan clears the plan view."""
    window = _make_window(None)
    window._poll_plan()

    window._left_sidebar.update_plan.assert_called_once_with([])


def test_poll_plan_without_loop_touches_no_sidebar():
    """No bound loop => the poll returns without pushing plan state."""
    window = _make_window(None, bound=False)
    window._poll_plan()

    window._left_sidebar.update_plan.assert_not_called()


def test_poll_plan_missing_plan_file_clears_left_sidebar(tmp_path):
    """A deleted plan file must clear the view instead of leaving a ghost."""
    missing = tmp_path / "gone.md"
    window = _make_window(str(missing))
    window._poll_plan()

    window._left_sidebar.update_plan.assert_called_once_with([])
