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
from pyside_gui.theme import qss


_CSS = qss("""
QWidget#session-history {
    background: @app_bg;
}
QLabel#sidebar-title {
    color: @fg_secondary;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px;
}
QListWidget {
    background: @app_bg;
    color: @fg;
    border: none;
    font-family: @font_ui;
    font-size: 13px;
    outline: none;
    padding: 0 6px;
}
QListWidget::item {
    border: none;
    border-radius: 8px;
}
QListWidget::item:hover {
    background: @hover_bg;
}
QListWidget::item:selected {
    background: @active_bg;
}
QLabel#session-title { color: @fg; font-family: @font_ui; font-size: 13px; }
QLabel#session-meta { color: @fg_tertiary; font-family: @font_ui; font-size: 11.5px; }
""")


class _SessionRow(QWidget):
    """Two-line history row: the session title, then a dim time · model line."""

    def __init__(self, title: str, meta: str) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(1)
        top = QLabel(title)
        top.setObjectName("session-title")
        bottom = QLabel(meta)
        bottom.setObjectName("session-meta")
        layout.addWidget(top)
        layout.addWidget(bottom)


class SessionHistoryView(QWidget):
    session_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("session-history")
        self.setStyleSheet(_CSS)

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
            title = (s.get("title") or "").strip() or Path(s.get("path", "?")).stem
            meta = (
                f"{s.get('started_at', '?')[:16].replace('T', ' ')}"
                f"  ·  {s.get('model', '?')}"
            )
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, s)
            item.setToolTip(title)
            row = _SessionRow(title[:80], meta)
            item.setSizeHint(row.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, row)

    def _on_item_selected(
        self, item: QListWidgetItem
    ) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.session_selected.emit(data)
