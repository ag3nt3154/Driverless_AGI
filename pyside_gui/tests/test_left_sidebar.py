from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from PySide6.QtWidgets import QSpacerItem

from pyside_gui.left_sidebar import LeftSidebar
from pyside_gui.sidebars.settings_view import SettingsView

_CONFIG = "agent_model: claude\ncontext_window: 1000  # tokens\n"


@pytest.fixture
def config_path(tmp_path):
    p = tmp_path / "dagi_root" / ".dagi" / "config.yaml"
    p.parent.mkdir(parents=True)
    p.write_text(_CONFIG, encoding="utf-8")
    return p


@pytest.fixture
def sidebar(qtbot, tmp_path, config_path):
    (tmp_path / ".dagi" / "logs").mkdir(parents=True)
    w = LeftSidebar(tmp_path, config_path=config_path)
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
    assert sidebar._panel.currentWidget() is sidebar._file_tree


def test_activate_history_loads_sessions(sidebar):
    with patch.object(
        sidebar._history_view, "load_sessions"
    ) as mock:
        sidebar.activate_view("history")
    mock.assert_called_once()
    assert sidebar._panel.currentWidget() is sidebar._history_view


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
    assert sidebar._panel.currentWidget() is sidebar._file_viewer


def test_set_project_path(sidebar, tmp_path):
    new_dir = tmp_path / "other"
    new_dir.mkdir()
    (new_dir / ".dagi" / "logs").mkdir(parents=True)
    with patch.object(
        sidebar._file_tree, "set_root"
    ) as mock:
        sidebar.set_project_path(new_dir)
    mock.assert_called_once_with(new_dir)


def test_rail_has_one_button_per_view(sidebar):
    # board, agents, files, viewer, plan, history, settings
    assert len(sidebar._rail_buttons) == 7
    assert sidebar._panel.count() == 7


def test_computer_use_false_has_no_workflows_view(sidebar):
    assert sidebar.workflows_view is None
    assert "workflows" not in sidebar._view_names


def test_rail_order(sidebar):
    assert sidebar._view_names == (
        "board", "agents", "files", "viewer", "plan", "history", "settings",
    )
    for name, btn in zip(sidebar._view_names, sidebar._rail_buttons):
        sidebar.activate_view(name)
        assert btn.isChecked()
    assert sidebar._panel.currentWidget() is sidebar.settings_view


def test_computer_use_true_adds_workflows_above_history(qtbot, tmp_path, config_path):
    (tmp_path / ".dagi" / "logs").mkdir(parents=True)
    w = LeftSidebar(tmp_path, computer_use=True, config_path=config_path)
    qtbot.addWidget(w)
    w.show()

    assert len(w._rail_buttons) == 8
    assert w._panel.count() == 8
    assert w._view_names[-3:] == ("workflows", "history", "settings")
    assert w.workflows_view is not None

    w.activate_view("workflows")
    assert w.is_expanded()
    assert w._panel.currentWidget() is w.workflows_view


def test_activate_plan_expands_to_plan_view(sidebar):
    sidebar.activate_view("plan")
    assert sidebar.is_expanded()
    assert sidebar._panel.isVisible()
    assert sidebar._panel.currentWidget() is sidebar._plan_view


def test_activate_plan_marks_rail_active(sidebar):
    sidebar.activate_view("plan")
    assert sidebar._rail_buttons[4].isChecked()
    assert not any(b.isChecked() for i, b in enumerate(sidebar._rail_buttons) if i != 4)


def test_activate_plan_twice_collapses(sidebar):
    sidebar.activate_view("plan")
    assert sidebar.is_expanded()
    sidebar.activate_view("plan")
    assert not sidebar.is_expanded()


def test_update_plan_delegates_to_plan_view(sidebar):
    subtasks = [{"name": "task a", "status": "complete"}]
    with patch.object(
        sidebar._plan_view, "update_plan"
    ) as mock:
        sidebar.update_plan(subtasks, title="My plan")
    mock.assert_called_once_with(subtasks, "My plan")


def test_session_selected_signal_bubbles(
    sidebar, qtbot
):
    with qtbot.waitSignal(
        sidebar.session_selected, timeout=1000
    ):
        sidebar._history_view.session_selected.emit(
            {"test": True}
        )


def test_panel_sizes_board_uses_given_width_other_views_split_evenly():
    from pyside_gui.left_sidebar import _RAIL_WIDTH, panel_sizes

    assert panel_sizes([_RAIL_WIDTH, 1000, 250], 250) == [_RAIL_WIDTH + 250, 1000 - 250, 250]
    assert panel_sizes([_RAIL_WIDTH, 1000, 250], None) == [_RAIL_WIDTH + 500, 500, 250]
    # the chat never drops below 200px
    assert panel_sizes([_RAIL_WIDTH, 300, 250], 250)[1] == 200


def test_view_changed_fires_for_rail_and_file_viewer(sidebar, tmp_path):
    seen = []
    sidebar.view_changed.connect(seen.append)
    sidebar.activate_view("board")
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    sidebar.open_file(str(f))
    assert seen == ["board", "viewer"]


# ── Settings ──


def test_activate_settings_shows_settings_view(sidebar, config_path):
    sidebar.activate_view("settings")
    assert sidebar.is_expanded()
    assert isinstance(sidebar.settings_view, SettingsView)
    assert sidebar._panel.currentWidget() is sidebar.settings_view
    assert sidebar._rail_buttons[-1].isChecked()
    assert not any(b.isChecked() for b in sidebar._rail_buttons[:-1])
    assert sidebar.settings_view._path == config_path


def test_stack_index_matches_view_name_index(sidebar):
    for i, name in enumerate(sidebar._view_names):
        sidebar.activate_view(name)
        assert sidebar._panel.currentIndex() == i


def test_settings_button_pinned_below_stretch(sidebar):
    layout = sidebar._rail_buttons[0].parentWidget().layout()
    n = layout.count()
    assert layout.itemAt(n - 1).widget() is sidebar._rail_buttons[-1]
    spacer = layout.itemAt(n - 2)
    assert spacer.widget() is None and isinstance(spacer.spacerItem(), QSpacerItem)
    # every other rail button sits above the stretch
    above = [layout.itemAt(i).widget() for i in range(n - 2)]
    assert above == sidebar._rail_buttons[:-1]
    btn = sidebar._rail_buttons[-1]
    assert btn.isCheckable()
    assert btn.toolTip() == "Settings"


def test_settings_button_click_toggles_panel(sidebar):
    sidebar._rail_buttons[-1].click()
    assert sidebar.active_view() == "settings"
    sidebar._rail_buttons[-1].click()
    assert not sidebar.is_expanded()


def test_activate_settings_reloads_when_clean(sidebar):
    with (
        patch.object(sidebar.settings_view, "is_dirty", return_value=False),
        patch.object(sidebar.settings_view, "reload") as mock,
    ):
        sidebar.activate_view("settings")
    mock.assert_called_once_with()


def test_activate_settings_keeps_edits_when_dirty(sidebar):
    with (
        patch.object(sidebar.settings_view, "is_dirty", return_value=True),
        patch.object(sidebar.settings_view, "reload") as mock,
    ):
        sidebar.activate_view("settings")
    mock.assert_not_called()


def test_settings_tooltip_reflects_dirty_state(sidebar):
    btn = sidebar._rail_buttons[-1]
    sidebar.settings_view.dirty_changed.emit(True)
    assert btn.toolTip() == "Settings (unsaved changes)"
    sidebar.settings_view.dirty_changed.emit(False)
    assert btn.toolTip() == "Settings"


def test_settings_does_not_write_config(sidebar, config_path):
    sidebar.activate_view("settings")
    sidebar.collapse()
    sidebar.activate_view("settings")
    assert config_path.read_text(encoding="utf-8") == _CONFIG
