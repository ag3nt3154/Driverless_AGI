from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QDir,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QFileSystemModel,
    QLabel,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

_HIDDEN_DIRS = {
    ".git", "__pycache__", "node_modules", ".mypy_cache",
}
_HIDDEN_DIR_PATHS = {"logs"}  # only under .dagi/
_HIDDEN_EXTENSIONS = {".pyc", ".pyo"}

_CSS = """
QWidget#file-tree {
    background: #1e1e2e;
}
QLabel#sidebar-title {
    color: #6c7086;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px;
}
QTreeView {
    background: #1e1e2e;
    color: #cdd6f4;
    border: none;
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 13px;
}
QTreeView::item {
    padding: 2px 4px;
}
QTreeView::item:hover {
    background: #313147;
}
QTreeView::item:selected {
    background: #1a3a5c;
}
QTreeView::branch {
    background: #1e1e2e;
}
"""


class _FilterProxy(QSortFilterProxyModel):
    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        model = self.sourceModel()
        idx = model.index(source_row, 0, source_parent)
        name = model.fileName(idx)
        is_dir = model.isDir(idx)
        if is_dir and name in _HIDDEN_DIRS:
            return False
        if is_dir:
            parent = model.filePath(source_parent)
            if (
                parent.replace("\\", "/").endswith(".dagi")
                and name in _HIDDEN_DIR_PATHS
            ):
                return False
        if not is_dir:
            suffix = Path(name).suffix.lower()
            if suffix in _HIDDEN_EXTENSIONS:
                return False
        return True

    def lessThan(
        self, left: QModelIndex, right: QModelIndex
    ) -> bool:
        model = self.sourceModel()
        left_dir = model.isDir(left)
        right_dir = model.isDir(right)
        if left_dir != right_dir:
            return left_dir
        return (
            model.fileName(left).lower()
            < model.fileName(right).lower()
        )


class FileTreeView(QWidget):
    file_selected = Signal(str)

    def __init__(self, project_path: Path) -> None:
        super().__init__()
        self.setObjectName("file-tree")
        self.setStyleSheet(_CSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("FILES")
        title.setObjectName("sidebar-title")
        layout.addWidget(title)

        self._fs_model = QFileSystemModel()
        self._fs_model.setFilter(
            QDir.Filter.AllDirs
            | QDir.Filter.Files
            | QDir.Filter.NoDotAndDotDot
            | QDir.Filter.Hidden
        )
        self._fs_model.setRootPath(str(project_path))

        self._proxy = _FilterProxy()
        self._proxy.setSourceModel(self._fs_model)
        self._proxy.sort(0, Qt.SortOrder.AscendingOrder)

        self._tree = QTreeView()
        self._tree.setModel(self._proxy)
        self._tree.setHeaderHidden(True)
        for col in range(1, self._fs_model.columnCount()):
            self._tree.hideColumn(col)
        self._tree.setSortingEnabled(True)
        self._tree.setAnimated(False)
        self._tree.setIndentation(16)

        source_root = self._fs_model.index(str(project_path))
        proxy_root = self._proxy.mapFromSource(source_root)
        self._tree.setRootIndex(proxy_root)

        self._tree.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree)

    def set_root(self, path: Path) -> None:
        self._fs_model.setRootPath(str(path))
        source_root = self._fs_model.index(str(path))
        proxy_root = self._proxy.mapFromSource(source_root)
        self._tree.setRootIndex(proxy_root)

    def _on_double_click(
        self, proxy_idx: QModelIndex
    ) -> None:
        source_idx = self._proxy.mapToSource(proxy_idx)
        if self._fs_model.isDir(source_idx):
            return
        path = self._fs_model.filePath(source_idx)
        self.file_selected.emit(path)
