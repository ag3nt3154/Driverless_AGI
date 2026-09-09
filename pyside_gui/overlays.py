from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from agent.history import build_copyable_messages

_OVERLAY_CSS = """
QWidget#overlay-backdrop {
    background: rgba(0, 0, 0, 180);
}
QWidget#overlay-panel {
    background: #282839;
    border: 1px solid #45475a;
    border-radius: 12px;
    padding: 16px;
}
QLabel { color: #cdd6f4; font-size: 14px; }
QLabel#overlay-title {
    color: #94e2d5;
    font-weight: bold;
    font-size: 16px;
}
QListWidget {
    background: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    font-size: 13px;
}
QListWidget::item { padding: 8px; }
QListWidget::item:hover { background: #313147; }
QListWidget::item:selected { background: #1a3a5c; }
"""


class CopyPicker(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("overlay-backdrop")
        self.setStyleSheet(_OVERLAY_CSS)
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        panel = QWidget()
        panel.setObjectName("overlay-panel")
        panel.setFixedWidth(600)
        panel_layout = QVBoxLayout(panel)

        title = QLabel("Copy a message")
        title.setObjectName("overlay-title")
        panel_layout.addWidget(title)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_copy)
        panel_layout.addWidget(self._list)

        self._messages_data: list[dict] = []
        layout.addWidget(panel)

    def show_messages(self, messages: list[dict]) -> None:
        self._list.clear()
        self._messages_data = build_copyable_messages(messages)
        for m in self._messages_data:
            preview = m.get("content", "")[:80].replace("\n", " ")
            label = f"[{m.get('label', '?')}] {preview}"
            self._list.addItem(label)
        self.show()
        self.raise_()

    def _on_copy(self, item: QListWidgetItem) -> None:
        idx = self._list.row(item)
        if 0 <= idx < len(self._messages_data):
            text = self._messages_data[idx].get("content", "")
            # Use Qt's cross-platform clipboard so this works on all OSes.
            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(text)
            self.hide()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.setGeometry(self.parent().rect())
