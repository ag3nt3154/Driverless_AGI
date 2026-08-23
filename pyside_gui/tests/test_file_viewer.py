from __future__ import annotations

from pathlib import Path

import pytest

from pyside_gui.sidebars.file_viewer import (
    FileViewerView,
    _MAX_FILE_SIZE,
)


@pytest.fixture
def viewer(qtbot):
    w = FileViewerView()
    qtbot.addWidget(w)
    return w


def test_open_python_file_shows_plain_text(viewer, tmp_path):
    f = tmp_path / "test.py"
    f.write_text("x = 1\ny = 2", encoding="utf-8")
    viewer.open_file(str(f), tmp_path)
    assert viewer._stack.currentIndex() == 0
    assert "x = 1" in viewer._text_edit.toPlainText()


def test_open_md_file_shows_markdown(viewer, tmp_path):
    f = tmp_path / "README.md"
    f.write_text("# Hello\n\nWorld", encoding="utf-8")
    viewer.open_file(str(f), tmp_path)
    assert viewer._stack.currentIndex() == 1


def test_header_shows_relative_path(viewer, tmp_path):
    f = tmp_path / "src" / "main.py"
    f.parent.mkdir()
    f.write_text("pass", encoding="utf-8")
    viewer.open_file(str(f), tmp_path)
    expected = str(Path("src") / "main.py")
    assert expected in viewer._path_label.text()


def test_large_file_shows_error(viewer, tmp_path):
    f = tmp_path / "big.txt"
    f.write_bytes(b"x" * (_MAX_FILE_SIZE + 1))
    viewer.open_file(str(f), tmp_path)
    assert viewer._stack.currentIndex() == 0
    assert "too large" in viewer._text_edit.toPlainText().lower()


def test_clear_resets(viewer, tmp_path):
    f = tmp_path / "test.py"
    f.write_text("code", encoding="utf-8")
    viewer.open_file(str(f), tmp_path)
    viewer.clear()
    assert viewer._text_edit.toPlainText() == ""
    assert viewer._path_label.text() == ""


def test_binary_file_replaces_errors(viewer, tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x80\x81\x82\xff")
    viewer.open_file(str(f), tmp_path)
    assert viewer._stack.currentIndex() == 0
    assert len(viewer._text_edit.toPlainText()) > 0


def test_open_nonexistent_file_shows_error(viewer, tmp_path):
    viewer.open_file("/nonexistent/path/file.py", tmp_path)
    assert "Cannot open file" in viewer._text_edit.toPlainText()
    assert viewer._stack.currentIndex() == 0
