from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

from pyside_gui.theme import qcolor, qss

_MAX_VISIBLE = 10
_ITEM_HEIGHT = 28
_HIGHLIGHT_FG = qcolor("fg")
_DIM_FG = qcolor("fg_secondary")

_POPUP_CSS = qss("""
QListWidget {
  background: @menu_bg;
  color: @fg;
  border: 1px solid @border;
  border-radius: 10px;
  padding: 4px;
  font-family: @font_ui;
  font-size: 13px;
  outline: none;
}
QListWidget::item {
  padding: 4px 8px;
  border-radius: 6px;
}
QListWidget::item:selected {
  background: @active_bg;
}
""")


class SlashCompleterPopup(QListWidget):
    """Filtered popup listing slash commands, skills, and workflows."""

    command_accepted = Signal(str)

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(_POPUP_CSS)
        self._all_items: list[tuple[str, str]] = []
        self.hide()

    def set_items(self, items: list[tuple[str, str]]) -> None:
        """Populate the list. Each item is (command_name, description)."""
        self._all_items = list(items)
        self.clear()
        for name, desc in self._all_items:
            label = f"{name}  {desc}" if desc else name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setForeground(QBrush(_HIGHLIGHT_FG))
            self.addItem(item)

    def apply_filter(self, prefix: str) -> None:
        """Show only items whose command name starts with *prefix*."""
        prefix_lower = prefix.lower()
        first_visible = -1
        for i in range(self.count()):
            item = self.item(i)
            name: str = item.data(Qt.ItemDataRole.UserRole)
            visible = name.lower().startswith(prefix_lower)
            item.setHidden(not visible)
            if visible and first_visible < 0:
                first_visible = i
        if first_visible >= 0:
            self.setCurrentRow(first_visible)
        self._resize_to_content()

    def _resize_to_content(self) -> None:
        rows = min(self.visible_count(), _MAX_VISIBLE)
        if rows == 0:
            self.hide()
            return
        self.show()
        self.setFixedHeight(rows * _ITEM_HEIGHT + 12)

    def selected_command(self) -> str | None:
        """Return the command name of the currently selected row."""
        item = self.currentItem()
        if item is None or item.isHidden():
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def move_selection(self, delta: int) -> None:
        """Move selection up (-1) or down (+1), wrapping and skipping hidden."""
        visible_indices = [
            i for i in range(self.count()) if not self.item(i).isHidden()
        ]
        if not visible_indices:
            return
        current = self.currentRow()
        try:
            pos = visible_indices.index(current)
        except ValueError:
            pos = 0
        pos = (pos + delta) % len(visible_indices)
        self.setCurrentRow(visible_indices[pos])

    def visible_count(self) -> int:
        return sum(1 for i in range(self.count()) if not self.item(i).isHidden())
