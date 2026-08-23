from __future__ import annotations

from unittest.mock import patch

import pytest

import pyside_gui  # noqa: F401 - must be imported before any PySide6 import

from pyside_gui.sidebars.session_history import SessionHistoryView


@pytest.fixture
def view(qtbot):
    w = SessionHistoryView()
    qtbot.addWidget(w)
    return w


def test_initial_state(view):
    assert view._list.count() == 0


def test_load_sessions_populates_list(view, tmp_path):
    fake_sessions = [
        {"started_at": "2026-08-23T10:00:00", "model": "test-model",
         "title": "Hello world", "path": str(tmp_path / "s1.jsonl")},
        {"started_at": "2026-08-23T11:00:00", "model": "test-model-2",
         "title": "", "path": str(tmp_path / "s2.jsonl")},
    ]
    with patch(
        "pyside_gui.sidebars.session_history.load_sessions",
        return_value=fake_sessions,
    ):
        view.load_sessions(tmp_path, max_sessions=10)
    assert view._list.count() == 2


def test_double_click_emits_signal(view, tmp_path, qtbot):
    fake_sessions = [
        {"started_at": "2026-08-23T10:00:00", "model": "m",
         "title": "t", "path": str(tmp_path / "s.jsonl")},
    ]
    with patch(
        "pyside_gui.sidebars.session_history.load_sessions",
        return_value=fake_sessions,
    ):
        view.load_sessions(tmp_path)
    with qtbot.waitSignal(
        view.session_selected, timeout=1000
    ) as blocker:
        view._list.itemDoubleClicked.emit(view._list.item(0))
    assert blocker.args[0]["model"] == "m"
