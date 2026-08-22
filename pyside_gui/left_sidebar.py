from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from agent.history import load_sessions

_LEFT_CSS = """
QWidget#left-sidebar {
    background: #1e1e2e;
    border-right: 1px solid #45475a;
}
QLabel#sidebar-title {
    color: #6c7086;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px;
}
QListWidget {
    background: #1e1e2e;
    color: #cdd6f4;
    border: none;
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 13px;
}
QListWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #313147;
}
QListWidget::item:hover {
    background: #313147;
}
QListWidget::item:selected {
    background: #1a3a5c;
}
"""


class LeftSidebar(QWidget):
    session_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("left-sidebar")
        self.setStyleSheet(_LEFT_CSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("SESSION HISTORY")
        title.setObjectName("sidebar-title")
        layout.addWidget(title)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(
            self._on_item_selected
        )
        layout.addWidget(self._list)

        self._sessions: list[dict] = []

    def load_sessions(
        self, logs_dir: Path, max_sessions: int = 20
    ) -> None:
        self._sessions = load_sessions(logs_dir, max_sessions)
        self._list.clear()
        for s in self._sessions:
            label = (
                f"{s.get('started_at', '?')[:16]}  "
                f"{s.get('model', '?')}"
            )
            title = s.get("title", "")
            if title:
                label += f"\n  {title[:60]}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, s)
            self._list.addItem(item)

    def _on_item_selected(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.session_selected.emit(data)

    def set_expanded(self, expanded: bool) -> None:
        self.setVisible(expanded)
