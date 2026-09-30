from __future__ import annotations

import sys
import time

import pytest
import pyside_gui  # noqa: F401 - register DLL paths before Qt imports
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from agent import notepad_store as store
from pyside_gui.notepad_controller import NotepadController

_app = QApplication.instance() or QApplication(sys.argv)


def _spin_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _external_write(root, text: str) -> None:
    # Another process (editor, dagi's write tool) replacing the file.
    store.write_text(text, root)


@pytest.fixture
def ctl(tmp_path):
    store.write_text("initial", tmp_path)
    controller = NotepadController(root=tmp_path, autosave_ms=50)
    yield controller
    controller.deleteLater()


def test_loads_existing_text(ctl):
    assert ctl.text() == "initial"
    assert not ctl.is_dirty()


def test_autosave_is_debounced(ctl, tmp_path):
    ctl.on_editor_changed("a")
    ctl.on_editor_changed("ab")
    assert ctl.is_dirty()
    assert store.read_text(tmp_path) == "initial"
    assert _spin_until(lambda: store.read_text(tmp_path) == "ab")
    assert not ctl.is_dirty()


def test_flush_writes_latest_text_immediately(ctl, tmp_path):
    ctl.on_editor_changed("typed")
    ctl.flush("typed more")
    assert store.read_text(tmp_path) == "typed more"
    assert not ctl.is_dirty()


def test_reverting_to_saved_text_is_not_dirty(ctl):
    ctl.on_editor_changed("x")
    ctl.on_editor_changed("initial")
    assert not ctl.is_dirty()


def test_save_as_writes_copy_only(ctl, tmp_path):
    ctl.flush("note body")
    out = ctl.save_as(tmp_path / "export" / "copy.md")
    assert out.read_text(encoding="utf-8") == "note body"
    assert store.read_text(tmp_path) == "note body"


def test_own_writes_do_not_trigger_reload(ctl):
    reloads = []
    ctl.external_reload.connect(reloads.append)
    ctl.flush("mine")
    _spin_until(lambda: False, timeout=0.5)
    assert reloads == []


def test_external_change_reloads_when_clean(ctl, tmp_path):
    reloads = []
    ctl.external_reload.connect(reloads.append)
    _external_write(tmp_path, "from outside")
    assert _spin_until(lambda: reloads == ["from outside"])
    assert ctl.text() == "from outside"


def test_external_change_while_dirty_backs_up_and_keeps_local(ctl, tmp_path):
    reloads, conflicts = [], []
    ctl.external_reload.connect(reloads.append)
    ctl.conflict_saved.connect(conflicts.append)
    ctl._timer.setInterval(60_000)  # keep local edits unsaved
    ctl.on_editor_changed("local edits")
    _external_write(tmp_path, "outside edits")
    assert _spin_until(lambda: len(conflicts) == 1)
    assert conflicts[0].read_text(encoding="utf-8") == "outside edits"
    assert store.read_text(tmp_path) == "local edits"
    assert reloads == []
    assert not ctl.is_dirty()


def test_watch_survives_repeated_replaces(ctl, tmp_path):
    reloads = []
    ctl.external_reload.connect(reloads.append)
    for i in range(3):
        _external_write(tmp_path, f"v{i}")
        assert _spin_until(lambda i=i: reloads and reloads[-1] == f"v{i}"), i


def test_starts_empty_without_file(tmp_path):
    controller = NotepadController(root=tmp_path / "fresh", autosave_ms=50)
    assert controller.text() == ""
    controller.flush("hello")
    assert store.read_text(tmp_path / "fresh") == "hello"
