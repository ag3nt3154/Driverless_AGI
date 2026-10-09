"""Agents rail view: spawn agents by slug, see their state, open one in the main chat."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
    QWidget,
)

from pyside_gui.theme import qss

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
RESERVED_SLUGS = frozenset({"main", "user"})
_LIST_CSS = qss("""
QListWidget {
    background: @app_bg; color: @fg; border: none; outline: none;
    font-family: @font_ui; font-size: 13px; padding: 0 6px;
}
QListWidget::item { border: none; border-radius: 8px; padding: 4px 2px; }
QListWidget::item:hover { background: @hover_bg; }
QListWidget::item:selected { background: @active_bg; color: @fg; }
""")
_DOTS = {"running": "🟢", "waiting": "🟠", "paused": "⏸", "error": "🔴", "idle": "⚪"}


def slug_error(slug: str, taken) -> str | None:
    """Why ``slug`` cannot name a new agent, or None when it can."""
    if not SLUG_RE.fullmatch(slug):
        return "Use 1–32 lowercase letters, digits or '-', starting with a letter or digit."
    if slug in RESERVED_SLUGS:
        return f"'{slug}' is reserved."
    if slug in taken:
        return f"An agent named '{slug}' already exists."
    return None


def _plain(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class AgentsView(QWidget):
    spawn_requested = Signal(str)     # slug
    activate_requested = Signal(str)  # handle
    close_requested = Signal(str)     # handle

    def __init__(self) -> None:
        super().__init__()
        self._taken: set[str] = set()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        header = _plain("AGENTS")
        header.setStyleSheet(qss("color: @fg_secondary; font-weight: bold; padding: 8px;"))
        outer.addWidget(header)
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 8, 0)
        self._slug = QLineEdit()
        self._slug.setPlaceholderText("new agent slug, e.g. researcher")
        self._slug.setMaxLength(32)
        self._slug.returnPressed.connect(self._spawn)
        self._spawn_button = QPushButton("Spawn")
        self._spawn_button.clicked.connect(self._spawn)
        row.addWidget(self._slug, 1)
        row.addWidget(self._spawn_button)
        outer.addLayout(row)
        self._error = _plain("")
        self._error.setWordWrap(True)
        self._error.setStyleSheet("color: #d55; padding: 0 8px;")
        self._error.hide()
        outer.addWidget(self._error)
        self._list = QListWidget()
        self._list.setStyleSheet(_LIST_CSS)
        self._list.setWordWrap(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemClicked.connect(self._on_clicked)
        self._list.currentItemChanged.connect(lambda *_: self._update_close())
        outer.addWidget(self._list, 1)
        self._close = QPushButton("Close agent")
        self._close.setEnabled(False)
        self._close.clicked.connect(self._close_selected)
        outer.addWidget(self._close)
        hint = _plain("Open an agent, run /wd <folder>, then send its first prompt.")
        hint.setWordWrap(True)
        hint.setStyleSheet(qss("color: @fg_tertiary; padding: 4px 8px 8px;"))
        outer.addWidget(hint)

    def set_agents(self, agents: list[dict]) -> None:
        """Rows of {handle, slug, state, folder, active, main}; keeps the selection."""
        current = self._list.currentItem()
        selected = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._list.clear()
        self._taken = {agent["slug"] for agent in agents}
        for agent in agents:
            marker = "▶ " if agent["active"] else "   "
            dot = _DOTS.get(agent["state"], _DOTS["idle"])
            state = "waiting for you" if agent["state"] == "waiting" else agent["state"]
            item = QListWidgetItem(f"{marker}{dot} {agent['handle']} — {state}")
            item.setToolTip(str(agent["folder"]))
            item.setData(Qt.ItemDataRole.UserRole, agent["handle"])
            item.setData(Qt.ItemDataRole.UserRole + 1, agent["main"])
            self._list.addItem(item)
            if agent["handle"] == selected:
                self._list.setCurrentItem(item)
        self._update_close()

    def show_error(self, text: str | None) -> None:
        self._error.setText(text or "")
        self._error.setVisible(bool(text))

    def _spawn(self) -> None:
        slug = self._slug.text().strip()
        error = slug_error(slug, self._taken)
        self.show_error(error)
        if error is None:
            self._slug.clear()
            self.spawn_requested.emit(slug)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        self.activate_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _update_close(self) -> None:
        item = self._list.currentItem()
        self._close.setEnabled(item is not None and not item.data(Qt.ItemDataRole.UserRole + 1))

    def _close_selected(self) -> None:
        item = self._list.currentItem()
        if item is not None and not item.data(Qt.ItemDataRole.UserRole + 1):
            self.close_requested.emit(item.data(Qt.ItemDataRole.UserRole))
