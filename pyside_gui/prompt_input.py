from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QPlainTextEdit


class PromptInput(QPlainTextEdit):
    """Multi-line input: Enter submits, Shift+Enter/Ctrl+N for newlines."""

    submitted = Signal(str)

    COLLAPSED_HEIGHT = 100
    BORDER_STYLE = (
        "QPlainTextEdit {"
        "  background: #282839;"
        "  color: #cdd6f4;"
        "  border: 1px solid #45475a;"
        "  border-radius: 8px;"
        "  padding: 8px;"
        "  font-family: 'Segoe UI', system-ui, sans-serif;"
        "  font-size: 14px;"
        "}"
        "QPlainTextEdit:focus {"
        "  border-color: #89b4fa;"
        "}"
    )

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText(
            "Type a message… (Enter to send, Shift+Enter for newline)"
        )
        self.setStyleSheet(self.BORDER_STYLE)
        self.setFixedHeight(self.COLLAPSED_HEIGHT)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        mods = event.modifiers()
        key = event.key()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & (
                Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.ControlModifier
            ):
                super().keyPressEvent(event)
                return
            text = self.toPlainText().strip()
            if text:
                self.submitted.emit(text)
            self.clear()
            event.accept()
            return

        super().keyPressEvent(event)

    def set_compose_mode(self, expanded: bool) -> None:
        if expanded:
            self.setMinimumHeight(200)
            self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
        else:
            self.setFixedHeight(self.COLLAPSED_HEIGHT)
