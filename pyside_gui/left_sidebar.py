from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pyside_gui.sidebars import (
    FileTreeView,
    FileViewerView,
    SessionHistoryView,
)

_VIEW_NAMES = ("history", "files", "viewer")
_RAIL_ICONS = ("\U0001f4cb", "\U0001f4c1", "\U0001f4c4")
_RAIL_WIDTH = 40
_PANEL_WIDTH = 280

_RAIL_CSS = """
QWidget#rail {{
    background: #181825;
    border-right: 1px solid #45475a;
}}
QPushButton {{
    background: transparent;
    color: {default_color};
    border: none;
    font-size: 18px;
    padding: 8px 0;
    min-height: 36px;
}}
QPushButton:hover {{
    color: #cdd6f4;
    background: #313147;
}}
"""

_ACTIVE_COLOR = "#89b4fa"
_DEFAULT_COLOR = "#6c7086"


class LeftSidebar(QWidget):
    session_selected = Signal(object)

    def __init__(self, project_path: Path) -> None:
        super().__init__()
        self._project_path = project_path
        self._active_view: str | None = None
        self._expanded = False

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        rail = QWidget()
        rail.setObjectName("rail")
        rail.setFixedWidth(_RAIL_WIDTH)
        rail.setStyleSheet(
            _RAIL_CSS.format(default_color=_DEFAULT_COLOR)
        )
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 4, 0, 4)
        rail_layout.setSpacing(0)
        rail_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._rail_buttons: list[QPushButton] = []
        for name, icon in zip(_VIEW_NAMES, _RAIL_ICONS):
            btn = QPushButton(icon)
            btn.setFixedSize(_RAIL_WIDTH, 36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda checked=False, n=name: (
                    self._on_rail_clicked(n)
                )
            )
            rail_layout.addWidget(btn)
            self._rail_buttons.append(btn)

        rail_layout.addStretch()
        root_layout.addWidget(rail)

        self._panel = QStackedWidget()
        self._panel.setFixedWidth(_PANEL_WIDTH)
        self._panel.setVisible(False)
        self._panel.setStyleSheet(
            "QStackedWidget {"
            "  border-right: 1px solid #45475a;"
            "}"
        )

        self._history_view = SessionHistoryView()
        self._file_tree = FileTreeView(project_path)
        self._file_viewer = FileViewerView()
        self._panel.addWidget(self._history_view)
        self._panel.addWidget(self._file_tree)
        self._panel.addWidget(self._file_viewer)

        self._file_tree.file_selected.connect(
            self._on_file_selected
        )
        self._history_view.session_selected.connect(
            self.session_selected.emit
        )

        root_layout.addWidget(self._panel)
        self.setFixedWidth(_RAIL_WIDTH)

    def activate_view(self, name: str) -> None:
        if name not in _VIEW_NAMES:
            return
        if name == self._active_view and self._expanded:
            self.collapse()
            return
        idx = _VIEW_NAMES.index(name)
        self._panel.setCurrentIndex(idx)
        self._active_view = name
        self._expanded = True
        self._panel.setVisible(True)
        self.setFixedWidth(_RAIL_WIDTH + _PANEL_WIDTH)
        self._update_rail_styles()
        if name == "history":
            logs = self._project_path / ".dagi" / "logs"
            if logs.is_dir():
                self._history_view.load_sessions(logs)

    def collapse(self) -> None:
        self._expanded = False
        self._active_view = None
        self._panel.setVisible(False)
        self.setFixedWidth(_RAIL_WIDTH)
        self._update_rail_styles()

    def is_expanded(self) -> bool:
        return self._expanded

    def set_project_path(self, path: Path) -> None:
        self._project_path = path
        self._file_tree.set_root(path)

    def open_file(self, path: str) -> None:
        self._file_viewer.open_file(path, self._project_path)
        self._active_view = "viewer"
        idx = _VIEW_NAMES.index("viewer")
        self._panel.setCurrentIndex(idx)
        self._expanded = True
        self._panel.setVisible(True)
        self.setFixedWidth(_RAIL_WIDTH + _PANEL_WIDTH)
        self._update_rail_styles()

    def _on_rail_clicked(self, name: str) -> None:
        self.activate_view(name)

    def _on_file_selected(self, path: str) -> None:
        self.open_file(path)

    def _update_rail_styles(self) -> None:
        for i, name in enumerate(_VIEW_NAMES):
            btn = self._rail_buttons[i]
            if name == self._active_view and self._expanded:
                btn.setStyleSheet(
                    f"color: {_ACTIVE_COLOR};"
                )
            else:
                btn.setStyleSheet("")
