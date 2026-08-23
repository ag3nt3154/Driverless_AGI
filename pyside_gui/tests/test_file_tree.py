from __future__ import annotations

from pathlib import Path

import pytest

from pyside_gui.sidebars.file_tree import FileTreeView


@pytest.fixture
def tree(qtbot, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "x = 1", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Hi", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-314.pyc").write_bytes(
        b"\x00"
    )
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("", encoding="utf-8")

    w = FileTreeView(tmp_path)
    qtbot.addWidget(w)
    return w


def test_root_is_set(tree, tmp_path):
    root_idx = tree._tree.rootIndex()
    model = tree._tree.model()
    source_idx = model.mapToSource(root_idx)
    path = tree._fs_model.filePath(source_idx)
    assert Path(path) == tmp_path


def test_set_root_changes_root(tree, tmp_path):
    new_dir = tmp_path / "src"
    tree.set_root(new_dir)
    root_idx = tree._tree.rootIndex()
    model = tree._tree.model()
    source_idx = model.mapToSource(root_idx)
    path = tree._fs_model.filePath(source_idx)
    assert Path(path) == new_dir


def test_hidden_dirs_filtered(tree, tmp_path, qtbot):
    proxy = tree._proxy
    fs = tree._fs_model
    qtbot.waitUntil(
        lambda: fs.rowCount(fs.index(str(tmp_path))) > 0,
        timeout=3000,
    )
    root_source = fs.index(str(tmp_path))
    root_proxy = proxy.mapFromSource(root_source)
    visible_names = []
    for row in range(proxy.rowCount(root_proxy)):
        idx = proxy.index(row, 0, root_proxy)
        visible_names.append(proxy.data(idx))
    assert ".git" not in visible_names
    assert "__pycache__" not in visible_names
    assert "src" in visible_names
    assert "README.md" in visible_names
