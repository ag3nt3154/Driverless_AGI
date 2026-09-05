"""pyside_gui/sidebars/plan_view.py — left-sidebar view showing the active plan.

Renders the active plan's title and one non-interactive, colour-coded row per
subtask. Data is pushed exclusively through ``PlanView.update_plan`` with the
``list[dict]`` shape returned by ``tools._plan_parser.parse_subtask_statuses``
(keys ``name`` / ``status``); identical snapshots are no-ops so the 2-second
GUI poll does not cause repaint churn.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

_STATUS_GLYPHS = {
    "pending": "[ ]",
    "in_progress": "[~]",
    "complete": "[x]",
    "failed": "[!]",
}
_STATUS_COLORS = {
    "pending": "#6c7086",
    "in_progress": "#f9e2af",
    "complete": "#a6e3a1",
    "failed": "#f38ba8",
}
_UNKNOWN_GLYPH = "[?]"
_UNKNOWN_COLOR = "#a6adc8"
_PLACEHOLDER_TEXT = "No active plan"

_CSS = """
QWidget#plan-view {
    background: #1e1e2e;
}
QLabel#sidebar-title {
    color: #6c7086;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px;
}
QLabel#plan-title {
    color: #cdd6f4;
    font-size: 13px;
    font-weight: bold;
    font-family: 'Segoe UI', system-ui, sans-serif;
    padding: 0 8px 6px 8px;
}
QListWidget {
    background: #1e1e2e;
    color: #cdd6f4;
    border: none;
    outline: none;
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 13px;
}
QListWidget::item {
    padding: 4px 8px;
    border-bottom: 1px solid #313147;
}
QListWidget::item:hover {
    background: transparent;
}
"""


class PlanView(QWidget):
    """Panel that shows the active plan title and per-subtask statuses."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("plan-view")
        self.setStyleSheet(_CSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("PLAN")
        header.setObjectName("sidebar-title")
        layout.addWidget(header)

        self._title_label = QLabel("")
        self._title_label.setObjectName("plan-title")
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setWordWrap(True)
        self._title_label.hide()
        layout.addWidget(self._title_label)

        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setSelectionMode(
            QListWidget.SelectionMode.NoSelection
        )
        layout.addWidget(self._list)

        self._snapshot: tuple = ()
        self._show_placeholder()

    def update_plan(
        self, subtasks: list[dict], title: str = ""
    ) -> None:
        """Replace the shown plan with *subtasks* and an optional *title*.

        *subtasks* follows the parser shape: each dict has ``name`` and
        ``status`` keys. An empty list restores the placeholder. Calling with
        an unchanged snapshot is a no-op.
        """
        snapshot = (
            title,
            tuple(
                (str(s.get("status", "unknown")), str(s.get("name", "")))
                for s in subtasks
            ),
        )
        if snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        self._list.clear()
        self._set_title(title)
        if not subtasks:
            self._show_placeholder()
            return
        for sub in subtasks:
            status = sub.get("status", "unknown")
            name = sub.get("name", "")
            glyph = _STATUS_GLYPHS.get(status, _UNKNOWN_GLYPH)
            colour = _STATUS_COLORS.get(status, _UNKNOWN_COLOR)
            item = QListWidgetItem(f"{glyph} {name}")
            item.setForeground(QBrush(QColor(colour)))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._list.addItem(item)

    def _set_title(self, title: str) -> None:
        self._title_label.setText(title)
        if title:
            self._title_label.show()
        else:
            self._title_label.hide()

    def _show_placeholder(self) -> None:
        item = QListWidgetItem(_PLACEHOLDER_TEXT)
        item.setForeground(QBrush(QColor("#6c7086")))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._list.addItem(item)
