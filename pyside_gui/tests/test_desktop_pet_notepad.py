from __future__ import annotations

import sys
import time

import pytest
import pyside_gui  # noqa: F401 - register DLL paths before Qt imports
from PySide6.QtCore import QCoreApplication, QPoint, QRect, QSize
from PySide6.QtWidgets import QApplication

from agent import notepad_store as store
from pyside_gui import desktop_pet
from pyside_gui.desktop_pet import (
    DEFAULT_NOTEPAD_SIZE, DesktopPetWindow, _PET_SIZE, expanded_geometry, pet_position,
)

_app = QApplication.instance() or QApplication(sys.argv)
SCREEN = QRect(0, 0, 1920, 1040)


def _spin_until(predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


# ── Pure geometry ─────────────────────────────────────────────────────────────

def test_expanded_geometry_centres_pet_above_notepad():
    rect = expanded_geometry(QPoint(800, 100), QSize(360, 444), SCREEN)
    assert rect.size() == QSize(360, _PET_SIZE.height() + 444)
    assert pet_position(rect) == QPoint(800, 100)


def test_expanded_geometry_shifts_up_and_left_to_stay_on_screen():
    # Default pet spot: bottom-right corner, 20 px inset.
    pet = QPoint(SCREEN.right() - 210 - 20, SCREEN.bottom() - 182 - 20)
    rect = expanded_geometry(pet, QSize(360, 444), SCREEN)
    assert SCREEN.contains(rect)
    assert rect.bottom() == SCREEN.bottom()
    assert rect.right() == SCREEN.right()


def test_expanded_geometry_clamps_top_left():
    rect = expanded_geometry(QPoint(-50, -30), QSize(360, 444), SCREEN)
    assert rect.topLeft() == QPoint(0, 0)


def test_narrow_notepad_uses_pet_width():
    rect = expanded_geometry(QPoint(500, 100), QSize(100, 300), SCREEN)
    assert rect.width() == _PET_SIZE.width()


# ── Window behaviour ─────────────────────────────────────────────────────────

@pytest.fixture
def pet(tmp_path, monkeypatch):
    monkeypatch.setattr(DesktopPetWindow, "_screen_rect", lambda self: SCREEN)
    window = DesktopPetWindow(notepad_root=tmp_path)
    window.move(1690, 838)
    window.show()
    yield window
    window._panel and window._panel.controller._timer.stop()
    window.close()
    window.deleteLater()
    _app.processEvents()


def test_starts_collapsed_without_editor(pet):
    assert not pet.is_expanded()
    assert pet.notepad_panel() is None
    assert pet.size() == _PET_SIZE


def test_expand_and_collapse_restore_pet_position(pet):
    start = pet.pos()
    pet.expand()
    assert pet.is_expanded()
    assert pet.size() == QSize(DEFAULT_NOTEPAD_SIZE.width(), _PET_SIZE.height() + DEFAULT_NOTEPAD_SIZE.height())
    assert SCREEN.contains(pet.geometry())
    pet.collapse()
    assert not pet.is_expanded()
    assert pet.size() == _PET_SIZE
    assert pet.pos() == start


def test_collapse_after_drag_keeps_pet_where_it_is_shown(pet):
    pet.expand()
    pet.move(100, 100)
    pet.collapse()
    assert pet.pos() == QPoint(100 + (DEFAULT_NOTEPAD_SIZE.width() - _PET_SIZE.width()) // 2, 100)


def test_resized_notepad_size_is_persisted(pet, tmp_path):
    pet.expand()
    pet.resize(500, _PET_SIZE.height() + 300)
    pet.collapse()
    assert store.load_state(tmp_path) == {"width": 500, "height": 300}
    reopened = DesktopPetWindow(notepad_root=tmp_path)
    assert reopened._notepad_size == QSize(500, 300)
    reopened.deleteLater()


def test_hide_collapses_and_reshow_stays_collapsed(pet):
    pet.expand()
    panel = pet.notepad_panel()
    pet.hide()
    assert not pet.is_expanded()
    pet.show()
    assert not pet.is_expanded()
    assert pet.notepad_panel() is panel  # editor kept, only hidden


def test_edits_are_flushed_on_hide(pet, tmp_path):
    pet.expand()
    panel = pet.notepad_panel()
    assert _spin_until(panel.editor.is_ready), "editor did not load"
    panel.editor.set_markdown("typed on the pad\n")
    pet.hide()
    assert _spin_until(lambda: "typed on the pad" in store.read_text(tmp_path))


def test_flush_notepad_async_without_panel_calls_done(pet):
    called = []
    pet.flush_notepad_async(lambda: called.append(True))
    assert called == [True]


def test_save_as_without_panel_copies_backing_file(pet, tmp_path, monkeypatch):
    store.write_text("saved note", tmp_path)
    target = tmp_path / "out.md"
    monkeypatch.setattr(desktop_pet.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    pet.save_as()
    assert target.read_text(encoding="utf-8") == "saved note"
