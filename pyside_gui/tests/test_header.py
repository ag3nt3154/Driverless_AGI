from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pyside_gui import recent_folders
from pyside_gui.header import ConversationHeader


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> Path:
    s = tmp_path / "recent.json"
    monkeypatch.setattr(recent_folders, "_STORE", s)
    return s


@pytest.fixture
def header(qtbot, store):
    h = ConversationHeader()
    qtbot.addWidget(h)
    return h


def _recent_actions(header: ConversationHeader) -> dict[str, object]:
    header.folder_menu().aboutToShow.emit()
    return {a.data(): a for a in header.folder_menu().actions() if a.data()}


def test_set_folder_shows_folder_name(header, tmp_path):
    header.set_folder(tmp_path / "Driverless_AGI")
    assert "Driverless_AGI" in header.folder_button().text()


def test_menu_lists_recents_with_current_checked_and_missing_disabled(header, tmp_path):
    here, there = tmp_path / "here", tmp_path / "there"
    here.mkdir()
    gone = tmp_path / "gone"
    there.mkdir()
    for p in (gone, there, here):
        recent_folders.push(p)
    header.set_folder(here)
    actions = _recent_actions(header)
    assert list(actions) == [str(here), str(there), str(gone)]
    assert actions[str(here)].isChecked()
    assert not actions[str(there)].isChecked()
    assert actions[str(there)].isEnabled()
    assert not actions[str(gone)].isEnabled()


def test_menu_rebuild_does_not_accumulate_entries(header, tmp_path):
    (tmp_path / "a").mkdir()
    recent_folders.push(tmp_path / "a")
    _recent_actions(header)
    n = len(header.folder_menu().actions())
    _recent_actions(header)
    assert len(header.folder_menu().actions()) == n


def test_clicking_recent_emits_folder_chosen(header, qtbot, tmp_path):
    (tmp_path / "a").mkdir()
    recent_folders.push(tmp_path / "a")
    action = _recent_actions(header)[str(tmp_path / "a")]
    with qtbot.waitSignal(header.folder_chosen) as sig:
        action.trigger()
    assert sig.args == [str(tmp_path / "a")]


def _named_action(header: ConversationHeader, prefix: str):
    header.folder_menu().aboutToShow.emit()
    return next(a for a in header.folder_menu().actions() if a.text().startswith(prefix))


def test_open_folder_emits_chosen_directory(header, qtbot, tmp_path):
    with patch("pyside_gui.header.QFileDialog.getExistingDirectory", return_value=str(tmp_path)):
        with qtbot.waitSignal(header.folder_chosen) as sig:
            _named_action(header, "Open Folder").trigger()
    assert sig.args == [str(tmp_path)]


def test_open_folder_cancel_emits_nothing(header, qtbot):
    with patch("pyside_gui.header.QFileDialog.getExistingDirectory", return_value=""):
        with qtbot.assertNotEmitted(header.folder_chosen):
            _named_action(header, "Open Folder").trigger()


def test_clear_recent_empties_store(header, tmp_path):
    (tmp_path / "a").mkdir()
    recent_folders.push(tmp_path / "a")
    _named_action(header, "Clear recent").trigger()
    assert recent_folders.load() == []


def test_main_window_records_startup_folder(qtbot, tmp_path):
    # Like VS Code, the folder dagi was launched in counts as "opened".
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from pyside_gui.app import DagiMainWindow

    win = DagiMainWindow.__new__(DagiMainWindow)
    win._project_path = tmp_path
    win._config = SimpleNamespace(display_name="model")
    win._cmd_handler = MagicMock()
    header = DagiMainWindow._build_header(win)
    qtbot.addWidget(header)
    assert recent_folders.load() == [tmp_path]
    assert tmp_path.name in header.folder_button().text()
