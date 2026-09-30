from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizeGrip, QToolButton, QVBoxLayout, QWidget,
)

from agent import notepad_store as store
from pyside_gui.notepad_controller import NotepadController
from pyside_gui.notepad_editor import NotepadEditor
from pyside_gui.theme import TOKENS, qss

HEADER_HEIGHT = 24
_NOTICE_MS = 5000
_SAVED_COLOR = TOKENS["success"]
_DIRTY_COLOR = TOKENS["warn"]

_STYLE = qss("""
#notepadPanel {
    background: @chat_bg;
    border: 1px solid @border;
    border-radius: 10px;
}
#notepadHeader { background: @app_bg; border-top-left-radius: 10px; border-top-right-radius: 10px; }
#notepadHeader QLabel { color: @fg_secondary; font-family: @font_ui; font-size: 12px; }
#notepadHeader QToolButton { color: @fg_secondary; border: none; font-size: 12px; padding: 0 6px; }
#notepadHeader QToolButton:hover { color: @danger; }
""")


class _Header(QFrame):
    """Title strip that doubles as a drag handle for the whole pet window."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("notepadHeader")
        self.setFixedHeight(HEADER_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_origin: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        event.accept()


class NotepadPanel(QFrame):
    """Header strip + Vditor editor + resize grip, wired to a NotepadController."""

    close_requested = Signal()
    save_as_requested = Signal()

    def __init__(self, root: Path = store.NOTEPAD_DIR, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("notepadPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(_STYLE)

        self.controller = NotepadController(root=root, parent=self)
        self.editor = NotepadEditor(self)

        header = _Header(self)
        title = QLabel("notepad")
        self._status = QLabel("●")
        self._status.setToolTip("Saved")
        self._notice = QLabel("")
        close_btn = QToolButton()
        close_btn.setText("✕")
        close_btn.setToolTip("Collapse notepad")
        close_btn.clicked.connect(self.close_requested)
        h = QHBoxLayout(header)
        h.setContentsMargins(10, 0, 4, 0)
        h.setSpacing(6)
        h.addWidget(title)
        h.addWidget(self._status)
        h.addWidget(self._notice, 1)
        h.addWidget(close_btn)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        grip_row.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.editor, 1)
        layout.addLayout(grip_row)

        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(lambda: self._notice.setText(""))

        self.editor.ready.connect(lambda: self.editor.set_markdown(self.controller.text()))
        self.editor.content_changed.connect(self.controller.on_editor_changed)
        self.editor.save_requested.connect(self.save_as_requested)
        self.controller.external_reload.connect(self.editor.set_markdown)
        self.controller.dirty_changed.connect(self._show_dirty)
        self.controller.conflict_saved.connect(self._show_conflict)
        self._show_dirty(False)

    def _show_dirty(self, dirty: bool) -> None:
        color = _DIRTY_COLOR if dirty else _SAVED_COLOR
        self._status.setStyleSheet(f"color: {color};")
        self._status.setToolTip("Unsaved changes" if dirty else "Saved")

    def _show_conflict(self, backup: Path) -> None:
        self._notice.setText(f"⚠ disk change → {Path(backup).name}")
        self._notice.setStyleSheet(f"color: {_DIRTY_COLOR};")
        self._notice_timer.start(_NOTICE_MS)

    def notice_text(self) -> str:
        return self._notice.text()

    # ── Flushing ─────────────────────────────────────────────────────────────

    def flush_async(self, done: Callable[[], None] | None = None) -> None:
        """Pull the editor's latest markdown (its input callback lags) and save it."""

        def _save(text) -> None:
            self.controller.flush(text if isinstance(text, str) else None)
            if done is not None:
                done()

        self.editor.fetch_markdown(_save)

    def flush_blocking(self, timeout_ms: int = 1000) -> None:
        loop = QEventLoop()
        finished: list[bool] = []
        self.flush_async(lambda: (finished.append(True), loop.quit()))
        if not finished:
            QTimer.singleShot(timeout_ms, loop.quit)
            loop.exec()
        if not finished:
            self.controller.flush()
