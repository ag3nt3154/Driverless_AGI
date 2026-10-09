"""Two-line board composer editor with @mention autocomplete."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from pyside_gui.slash_completer import SlashCompleterPopup

# The partial mention right before the cursor: "@" plus handle characters typed so far.
_PARTIAL = re.compile(r"(?:^|(?<=[\s(]))@([a-z0-9_-]*)$")


def mention_prefix(text_before_cursor: str) -> str | None:
    """``@partial`` being typed at the cursor, or None when the cursor is not in a mention."""
    match = _PARTIAL.search(text_before_cursor)
    return None if match is None else "@" + match.group(1)


class MentionEdit(QPlainTextEdit):
    """Plain-text box, two lines tall. Enter sends, Shift+Enter breaks the line.

    Typing ``@`` opens a popup of known handles; Tab/Enter accepts, Up/Down moves, Esc closes.
    """

    submitted = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        lines = QFontMetrics(self.font()).lineSpacing() * 2
        margins = self.contentsMargins()
        frame = int(self.document().documentMargin() * 2) + margins.top() + margins.bottom()
        self.setFixedHeight(lines + frame + 4)
        self.completer = SlashCompleterPopup(self)
        self.completer.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self.textChanged.connect(self._update_completer)
        self.cursorPositionChanged.connect(self._update_completer)

    # QLineEdit-compatible helpers used by the board view and its tests.
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:  # noqa: N802 - mirrors QLineEdit
        self.setPlainText(text)
        self.moveCursor(QTextCursor.MoveOperation.End)

    def set_mentions(self, handles: list[str]) -> None:
        self.completer.set_items([(f"@{handle}", "") for handle in handles])

    def _prefix(self) -> str | None:
        cursor = self.textCursor()
        block = cursor.block().text()[: cursor.positionInBlock()]
        return mention_prefix(block)

    def _update_completer(self) -> None:
        prefix = self._prefix()
        if prefix is None:
            self.completer.hide()
            return
        self.completer.apply_filter(prefix)
        if self.completer.isVisible():
            width = max(self.width(), 220)
            self.completer.setFixedWidth(width)
            top_left = self.mapToGlobal(self.rect().topLeft())
            self.completer.move(top_left.x(), top_left.y() - self.completer.height() - 4)

    def accept_completion(self) -> bool:
        """Replace the partial mention at the cursor with the selected handle."""
        choice = self.completer.selected_command()
        prefix = self._prefix()
        if choice is None or prefix is None:
            return False
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Left,
                            QTextCursor.MoveMode.KeepAnchor, len(prefix))
        cursor.insertText(choice + " ")
        self.setTextCursor(cursor)
        self.completer.hide()
        return True

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        key, mods = event.key(), event.modifiers()
        if self.completer.isVisible():
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                    not mods & Qt.KeyboardModifier.ShiftModifier:
                if self.accept_completion():
                    event.accept()
                    return
            if key == Qt.Key.Key_Escape:
                self.completer.hide()
                event.accept()
                return
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self.completer.move_selection(1 if key == Qt.Key.Key_Down else -1)
                event.accept()
                return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self.insertPlainText("\n")
            else:
                self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.completer.hide()
        super().focusOutEvent(event)
