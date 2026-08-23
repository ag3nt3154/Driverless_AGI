from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pyside_gui.left_sidebar import LeftSidebar


@pytest.fixture
def sidebar(qtbot, tmp_path):
    (tmp_path / ".dagi" / "logs").mkdir(parents=True)
    w = LeftSidebar(tmp_path)
    qtbot.addWidget(w)
    w.show()
    return w


def test_initial_state_collapsed(sidebar):
    assert not sidebar.is_expanded()
    assert not sidebar._panel.isVisible()


def test_activate_view_expands(sidebar):
    sidebar.activate_view("files")
    assert sidebar.is_expanded()
    assert sidebar._panel.isVisible()
    assert sidebar._panel.currentIndex() == 1


def test_activate_history_loads_sessions(sidebar):
    with patch.object(
        sidebar._history_view, "load_sessions"
    ) as mock:
        sidebar.activate_view("history")
    mock.assert_called_once()
    assert sidebar._panel.currentIndex() == 0


def test_activate_same_view_collapses(sidebar):
    sidebar.activate_view("files")
    assert sidebar.is_expanded()
    sidebar.activate_view("files")
    assert not sidebar.is_expanded()


def test_collapse(sidebar):
    sidebar.activate_view("files")
    sidebar.collapse()
    assert not sidebar.is_expanded()


def test_open_file_switches_to_viewer(sidebar, tmp_path):
    f = tmp_path / "test.py"
    f.write_text("x = 1", encoding="utf-8")
    sidebar.open_file(str(f))
    assert sidebar.is_expanded()
    assert sidebar._panel.currentIndex() == 2


def test_set_project_path(sidebar, tmp_path):
    new_dir = tmp_path / "other"
    new_dir.mkdir()
    (new_dir / ".dagi" / "logs").mkdir(parents=True)
    with patch.object(
        sidebar._file_tree, "set_root"
    ) as mock:
        sidebar.set_project_path(new_dir)
    mock.assert_called_once_with(new_dir)


def test_rail_has_three_buttons(sidebar):
    assert len(sidebar._rail_buttons) == 3


def test_session_selected_signal_bubbles(
    sidebar, qtbot
):
    with qtbot.waitSignal(
        sidebar.session_selected, timeout=1000
    ):
        sidebar._history_view.session_selected.emit(
            {"test": True}
        )
