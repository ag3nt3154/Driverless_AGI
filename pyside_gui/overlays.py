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
from pyside_gui.esc_stop import claim_escape
from pyside_gui.theme import qss

_OVERLAY_CSS = qss("""
QWidget#overlay-backdrop {
    background: @scrim;
}
QWidget#overlay-panel {
    background: @popover_bg;
    border: 1px solid @border;
    border-radius: 16px;
    padding: 16px;
}
QLabel { color: @fg; font-family: @font_ui; font-size: 14px; }
QLabel#overlay-title {
    color: @fg;
    font-weight: 600;
    font-size: 16px;
}
QListWidget {
    background: @app_bg;
    color: @fg;
    border: 1px solid @border;
    border-radius: 10px;
    font-family: @font_ui;
    font-size: 13px;
    outline: none;
}
QListWidget::item { padding: 8px; border-radius: 6px; }
QListWidget::item:hover { background: @hover_bg; }
QListWidget::item:selected { background: @active_bg; color: @fg; }
""")


class CopyPicker(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        claim_escape(self)
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
