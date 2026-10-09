from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pyside_gui.icons import icon
from pyside_gui.theme import qss

from pyside_gui.sidebars import (
    AgentsView,
    FileTreeView,
    FileViewerView,
    MessageBoardView,
    PlanView,
    SessionHistoryView,
)

_VIEW_NAMES = ("history", "files", "viewer", "plan", "board", "agents")
_RAIL_ICONS = ("history", "folder", "file", "plan", "board", "agents")
_RAIL_TIPS = ("Session history", "Files", "File viewer", "Plan", "Message board", "Agents")
_RAIL_WIDTH = 44

_RAIL_CSS = qss("""
QWidget#rail {
    background: @app_bg;
    border-right: 1px solid @border;
}
QToolButton {
    background: transparent;
    border: none;
    border-radius: 8px;
}
QToolButton:hover { background: @hover_bg; }
QToolButton:checked { background: @active_bg; }
""")

_PANEL_CSS = qss("""
QStackedWidget#left-panel {
    background: @app_bg;
    border-right: 1px solid @border;
}
""")


class LeftSidebar(QWidget):
    session_selected = Signal(object)
    expansion_changed = Signal(bool)
    view_changed = Signal(str)

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
        rail.setStyleSheet(_RAIL_CSS)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(5, 8, 5, 8)
        rail_layout.setSpacing(2)
        rail_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._rail_buttons: list[QToolButton] = []
        for name, glyph, tip in zip(_VIEW_NAMES, _RAIL_ICONS, _RAIL_TIPS):
            btn = QToolButton()
            btn.setIcon(icon(glyph, 18))
            btn.setIconSize(QSize(18, 18))
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.setFixedSize(34, 34)
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
        self._panel.setVisible(False)
        self._panel.setObjectName("left-panel")
        self._panel.setStyleSheet(_PANEL_CSS)

        self._history_view = SessionHistoryView()
        self._file_tree = FileTreeView(project_path)
        self._file_viewer = FileViewerView()
        self._plan_view = PlanView()
        self._board_view = MessageBoardView()
        self._agents_view = AgentsView()
        self._panel.addWidget(self._history_view)
        self._panel.addWidget(self._file_tree)
        self._panel.addWidget(self._file_viewer)
        self._panel.addWidget(self._plan_view)
        self._panel.addWidget(self._board_view)
        self._panel.addWidget(self._agents_view)

        self._file_tree.file_selected.connect(
            self._on_file_selected
        )
        self._history_view.session_selected.connect(
            self.session_selected.emit
        )

        root_layout.addWidget(self._panel, stretch=1)
        self.setMinimumWidth(_RAIL_WIDTH)

    def activate_view(self, name: str) -> None:
        if name not in _VIEW_NAMES:
            return
        if name == self._active_view and self._expanded:
            self.collapse()
            return
        idx = _VIEW_NAMES.index(name)
        self._panel.setCurrentIndex(idx)
        self._active_view = name
        if not self._expanded:
            self._expanded = True
            self._panel.setVisible(True)
            self.expansion_changed.emit(True)
        self._update_rail_styles()
        self.view_changed.emit(name)
        if name == "history":
            logs = self._project_path / ".dagi" / "logs"
            if logs.is_dir():
                self._history_view.load_sessions(logs)

    def collapse(self) -> None:
        self._expanded = False
        self._active_view = None
        self._panel.setVisible(False)
        self.expansion_changed.emit(False)
        self._update_rail_styles()

    def active_view(self) -> str | None:
        return self._active_view

    def is_expanded(self) -> bool:
        return self._expanded

    def set_project_path(self, path: Path) -> None:
        self._project_path = path
        self._file_tree.set_root(path)

    def open_file(self, path: str, line: int | None = None) -> None:
        self._file_viewer.open_file(path, self._project_path, line=line)
        self._active_view = "viewer"
        idx = _VIEW_NAMES.index("viewer")
        self._panel.setCurrentIndex(idx)
        if not self._expanded:
            self._expanded = True
            self._panel.setVisible(True)
            self.expansion_changed.emit(True)
        self._update_rail_styles()
        self.view_changed.emit("viewer")

    @property
    def board_view(self) -> MessageBoardView:
        return self._board_view

    @property
    def agents_view(self) -> AgentsView:
        return self._agents_view

    def update_plan(self, subtasks: list[dict], title: str = "") -> None:
        """Push plan data to the plan view (delegation for main-window code)."""
        self._plan_view.update_plan(subtasks, title)

    def _on_rail_clicked(self, name: str) -> None:
        self.activate_view(name)

    def _on_file_selected(self, path: str) -> None:
        self.open_file(path)

    def _update_rail_styles(self) -> None:
        for name, btn in zip(_VIEW_NAMES, self._rail_buttons):
            btn.setChecked(name == self._active_view and self._expanded)


def panel_sizes(sizes: list[int], narrow_width: int | None) -> list[int]:
    """Splitter sizes [left, main, right] for an expanded left sidebar.

    ``narrow_width`` gives the panel a fixed width (the message board opens as
    wide as the right sidebar); ``None`` splits the space with the chat
    evenly. The chat keeps at least 200px; the user can drag either way after.
    """
    total = sizes[0] + sizes[1]
    panel = narrow_width if narrow_width is not None else (total - _RAIL_WIDTH) // 2
    left = min(_RAIL_WIDTH + panel, total - 200)
    return [left, total - left, sizes[2]]
