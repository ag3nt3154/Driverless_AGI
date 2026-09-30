"""Slim bar above the conversation: sidebar toggles and a dim title."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from pyside_gui.icons import icon
from pyside_gui.theme import qss

HEADER_HEIGHT = 40

_CSS = qss("""
QWidget#conversation-header { background: @chat_bg; }
QLabel#conversation-title { color: @fg_tertiary; font-family: @font_ui; font-size: 12.5px; }
QToolButton#panel-toggle { background: transparent; border: none; border-radius: 7px; }
QToolButton#panel-toggle:hover { background: @hover_bg; }
""")


class ConversationHeader(QWidget):
    left_toggled = Signal()
    right_toggled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("conversation-header")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_CSS)
        self.setFixedHeight(HEADER_HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 0)

        row.addWidget(self._toggle("panel_left", "Toggle left sidebar", self.left_toggled))
        row.addStretch(1)
        self._title = QLabel()
        self._title.setObjectName("conversation-title")
        row.addWidget(self._title)
        row.addStretch(1)
        row.addWidget(self._toggle("panel_right", "Toggle right sidebar", self.right_toggled))

    @staticmethod
    def _toggle(name: str, tip: str, signal) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("panel-toggle")
        btn.setIcon(icon(name, 18))
        btn.setIconSize(QSize(18, 18))
        btn.setFixedSize(30, 30)
        btn.setToolTip(tip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _checked=False: signal.emit())
        return btn

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def title(self) -> str:
        return self._title.text()
