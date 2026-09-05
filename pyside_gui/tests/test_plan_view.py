from __future__ import annotations

import pytest

import pyside_gui  # noqa: F401 - must be imported before any PySide6 import

from PySide6.QtCore import Qt

from pyside_gui.sidebars.plan_view import (
    PlanView,
    _PLACEHOLDER_TEXT,
    _STATUS_COLORS,
    _STATUS_GLYPHS,
    _UNKNOWN_COLOR,
    _UNKNOWN_GLYPH,
)

_SAMPLE_SUBTASKS = [
    {"name": "Add PlanView widget", "status": "complete"},
    {"name": "Integrate into LeftSidebar", "status": "in_progress"},
    {"name": "Re-route plan updates", "status": "pending"},
    {"name": "Broken step", "status": "failed"},
]


@pytest.fixture
def view(qtbot):
    w = PlanView()
    qtbot.addWidget(w)
    return w


def _row_texts(view) -> list[str]:
    return [view._list.item(i).text() for i in range(view._list.count())]


def test_initial_state_shows_placeholder(view):
    assert view._list.count() == 1
    item = view._list.item(0)
    assert item.text() == _PLACEHOLDER_TEXT
    # Placeholder is not selectable/clickable.
    assert not (item.flags() & Qt.ItemFlag.ItemIsSelectable)
    assert view._title_label.text() == ""


def test_update_plan_renders_one_colour_coded_row_per_subtask(view):
    view.update_plan(_SAMPLE_SUBTASKS, title="Plan: gui-plan-sidebar-tab")

    assert view._title_label.text() == "Plan: gui-plan-sidebar-tab"
    assert view._list.count() == len(_SAMPLE_SUBTASKS)
    for idx, sub in enumerate(_SAMPLE_SUBTASKS):
        item = view._list.item(idx)
        status = sub["status"]
        assert item.text() == f"{_STATUS_GLYPHS[status]} {sub['name']}"
        assert (
            item.foreground().color().name()
            == _STATUS_COLORS[status]
        )


def test_rows_are_not_selectable(view):
    view.update_plan(_SAMPLE_SUBTASKS)
    assert (
        view._list.selectionMode()
        == view._list.SelectionMode.NoSelection
    )
    for i in range(view._list.count()):
        item = view._list.item(i)
        assert not (item.flags() & Qt.ItemFlag.ItemIsSelectable)


def test_clear_returns_to_placeholder(view):
    view.update_plan(_SAMPLE_SUBTASKS, title="Plan: something")
    assert view._list.count() == len(_SAMPLE_SUBTASKS)

    view.update_plan([], "")

    assert view._list.count() == 1
    assert view._list.item(0).text() == _PLACEHOLDER_TEXT
    assert view._title_label.text() == ""


def test_unknown_status_renders_fallback_without_dropping_row(view):
    view.update_plan(
        [{"name": "Mystery step", "status": "banana"}],
        title="Plan: odd",
    )

    assert view._list.count() == 1
    item = view._list.item(0)
    assert item.text() == f"{_UNKNOWN_GLYPH} Mystery step"
    assert item.foreground().color().name() == _UNKNOWN_COLOR
    assert view._title_label.text() == "Plan: odd"


def test_identical_snapshot_is_noop(view):
    view.update_plan(_SAMPLE_SUBTASKS, title="Plan: same")
    first_item = view._list.item(0)

    view.update_plan(_SAMPLE_SUBTASKS, title="Plan: same")

    # Widgets were not rebuilt: the original item object is still in place.
    assert view._list.item(0) is first_item
    assert view._list.count() == len(_SAMPLE_SUBTASKS)
