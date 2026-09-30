"""Slim bar above the conversation: sidebar toggles, folder picker and a dim title."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMenu, QToolButton, QWidget

from pyside_gui import recent_folders
from pyside_gui.icons import icon
from pyside_gui.menu_style import MENU_STYLESHEET
from pyside_gui.theme import qss

HEADER_HEIGHT = 40

_CSS = qss("""
QWidget#conversation-header { background: @chat_bg; }
QLabel#conversation-title { color: @fg_tertiary; font-family: @font_ui; font-size: 12.5px; }
QToolButton#panel-toggle { background: transparent; border: none; border-radius: 7px; }
QToolButton#panel-toggle:hover { background: @hover_bg; }
QToolButton#folder-button {
    background: transparent; border: none; border-radius: 7px; padding: 0 8px;
    color: @fg_secondary; font-family: @font_ui; font-size: 12.5px;
}
QToolButton#folder-button:hover { background: @hover_bg; color: @fg; }
QToolButton#folder-button::menu-indicator { image: none; width: 0; }
""")


class ConversationHeader(QWidget):
    left_toggled = Signal()
    right_toggled = Signal()
    folder_chosen = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("conversation-header")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_CSS)
        self.setFixedHeight(HEADER_HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 0)

        row.addWidget(self._toggle("panel_left", "Toggle left sidebar", self.left_toggled))
        self._folder: Path | None = None
        row.addWidget(self._build_folder_button())
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

    def _build_folder_button(self) -> QToolButton:
        self._folder_menu = QMenu(self)
        # Missing recent folders are disabled; make that visible (greyed, not just inert).
        self._folder_menu.setStyleSheet(
            MENU_STYLESHEET + qss("QMenu::item:disabled { color: @fg_tertiary; }")
        )
        self._folder_menu.aboutToShow.connect(self._rebuild_folder_menu)
        btn = QToolButton()
        btn.setObjectName("folder-button")
        btn.setIcon(icon("folder", 16))
        btn.setIconSize(QSize(16, 16))
        btn.setFixedHeight(30)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMenu(self._folder_menu)
        self._folder_button = btn
        return btn

    def _rebuild_folder_menu(self) -> None:
        menu = self._folder_menu
        menu.clear()
        menu.addAction("Open Folder…", self._open_folder_dialog)
        recents = recent_folders.load()
        if recents:
            menu.addSeparator()
        current = self._folder.resolve() if self._folder else None
        for path in recents:
            # "&" is a mnemonic marker in QAction text; double it to show literally.
            action = menu.addAction(f"{path.name}\t{path}".replace("&", "&&"))
            action.setData(str(path))
            action.setCheckable(True)
            action.setChecked(path == current)
            action.setEnabled(path.is_dir())
            action.triggered.connect(lambda _c=False, p=str(path): self.folder_chosen.emit(p))
        if recents:
            menu.addSeparator()
            menu.addAction("Clear recent", recent_folders.clear)

    def _open_folder_dialog(self) -> None:
        start = str(self._folder) if self._folder else ""
        chosen = QFileDialog.getExistingDirectory(self, "Open Folder", start)
        if chosen:
            self.folder_chosen.emit(chosen)

    def set_folder(self, path: Path) -> None:
        self._folder = path
        self._folder_button.setText(f"{path.name or path}  ▾")
        self._folder_button.setToolTip(f"{path}\nOpen folder or switch to a recent one")

    def folder_button(self) -> QToolButton:
        return self._folder_button

    def folder_menu(self) -> QMenu:
        return self._folder_menu

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def title(self) -> str:
        return self._title.text()
