from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Slot
from PySide6.QtGui import QContextMenuEvent, QImageReader, QMovie, QMouseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMenu, QVBoxLayout, QWidget

from agent import DAGI_ROOT
from agent import notepad_store as store
from pyside_gui.menu_style import MENU_STYLESHEET

_LOGGER = logging.getLogger(__name__)

_PET_SIZE = QSize(210, 182)
_EDGE_INSET = 20
_GIF_SUFFIXES = frozenset({".gif"})
DEFAULT_NOTEPAD_SIZE = QSize(360, 444)  # header strip + ~420 px editor
_MIN_NOTEPAD_SIZE = QSize(_PET_SIZE.width(), 160)
_QWIDGETSIZE_MAX = (1 << 24) - 1


def _scan_gifs(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in _GIF_SUFFIXES)


def expanded_geometry(pet_pos: QPoint, notepad: QSize, screen: QRect) -> QRect:
    """Window rect for the expanded pet: pet centred above the notepad, kept on screen."""
    width = max(_PET_SIZE.width(), notepad.width())
    height = _PET_SIZE.height() + notepad.height()
    x = pet_pos.x() + (_PET_SIZE.width() - width) // 2
    y = pet_pos.y()
    x = max(screen.left(), min(x, screen.right() + 1 - width))
    y = max(screen.top(), min(y, screen.bottom() + 1 - height))
    return QRect(x, y, width, height)


def pet_position(window: QRect) -> QPoint:
    """Screen position of the pet inside an expanded window rect."""
    return QPoint(window.x() + (window.width() - _PET_SIZE.width()) // 2, window.y())


class DesktopPetWindow(QWidget):
    """Frameless always-on-top pet that cycles VAD emote GIFs, with a collapsible notepad.

    Right-click the pet for the notepad menu. The notepad editor is created lazily
    on first open and only hidden on collapse, so reopening keeps undo history.
    """

    def __init__(self, notepad_root: Path = store.NOTEPAD_DIR) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_PET_SIZE)

        self._drag_origin: QPoint | None = None
        self._movie: QMovie | None = None
        self._seen_last_frame = False
        self._gifs = _scan_gifs(DAGI_ROOT / ".dagi" / "emotes" / "vad")
        self._last_index: int | None = None

        self._notepad_root = notepad_root
        self._panel = None  # NotepadPanel, built on first expand
        self._expanded = False
        self._collapsed_pos: QPoint | None = None
        self._expanded_pos: QPoint | None = None
        self._save_dir: Path | None = None
        saved = store.load_state(notepad_root)
        self._notepad_size = QSize(
            max(_MIN_NOTEPAD_SIZE.width(), int(saved.get("width", DEFAULT_NOTEPAD_SIZE.width()))),
            max(_MIN_NOTEPAD_SIZE.height(), int(saved.get("height", DEFAULT_NOTEPAD_SIZE.height()))),
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setFixedSize(_PET_SIZE)
        self._layout.addWidget(self._label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._move_to_default()

    def _move_to_default(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.right() - _PET_SIZE.width() - _EDGE_INSET
        y = geo.bottom() - _PET_SIZE.height() - _EDGE_INSET
        self.move(x, y)

    def _screen_rect(self) -> QRect:
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)

    # ── Notepad ───────────────────────────────────────────────────────────────

    def set_save_dir(self, path: Path | None) -> None:
        """Starting folder for the Save-as dialog (the current project)."""
        self._save_dir = path

    def is_expanded(self) -> bool:
        return self._expanded

    def notepad_panel(self):
        return self._panel

    def _ensure_panel(self):
        if self._panel is None:
            from pyside_gui.notepad_panel import NotepadPanel

            self._panel = NotepadPanel(root=self._notepad_root, parent=self)
            self._panel.close_requested.connect(self.collapse)
            self._panel.save_as_requested.connect(self.save_as)
            self._layout.addWidget(self._panel, 1)
            self._panel.hide()
        return self._panel

    def expand(self) -> None:
        if self._expanded:
            return
        panel = self._ensure_panel()
        self._collapsed_pos = self.pos()
        rect = expanded_geometry(self.pos(), self._notepad_size, self._screen_rect())
        self._expanded = True
        self.setMinimumSize(max(_PET_SIZE.width(), _MIN_NOTEPAD_SIZE.width()),
                            _PET_SIZE.height() + _MIN_NOTEPAD_SIZE.height())
        self.setMaximumSize(_QWIDGETSIZE_MAX, _QWIDGETSIZE_MAX)
        panel.show()
        self.setGeometry(rect)
        self._expanded_pos = self.pos()
        panel.editor.focus_editor()

    def collapse(self) -> None:
        if not self._expanded:
            return
        self._remember_size()
        self._panel.flush_async()
        moved = self.pos() != self._expanded_pos
        target = pet_position(self.geometry()) if moved or self._collapsed_pos is None else self._collapsed_pos
        self._expanded = False
        self._panel.hide()
        self.setFixedSize(_PET_SIZE)
        self.move(target)

    def toggle_notepad(self) -> None:
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def _remember_size(self) -> None:
        if not self._expanded:
            return
        self._notepad_size = QSize(self.width(), self.height() - _PET_SIZE.height())
        try:
            store.save_state(
                {"width": self._notepad_size.width(), "height": self._notepad_size.height()},
                self._notepad_root,
            )
        except OSError:
            _LOGGER.exception("Failed to save notepad state")

    def flush_notepad_async(self, done: Callable[[], None]) -> None:
        """Persist unsaved notepad edits, then call *done* (immediately if never opened)."""
        if self._panel is None:
            done()
        else:
            self._panel.flush_async(done)

    @Slot()
    def save_as(self) -> None:
        start = str(self._save_dir / "notepad.md") if self._save_dir else "notepad.md"
        path, _ = QFileDialog.getSaveFileName(self, "Save notepad as", start, "Markdown (*.md);;All files (*)")
        if not path:
            return
        if self._panel is None:
            store.atomic_write(Path(path), store.read_text(self._notepad_root))
            return
        self._panel.flush_async(lambda: self._panel.controller.save_as(Path(path)))

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLESHEET)
        menu.addAction("Close notepad" if self._expanded else "Open notepad", self.toggle_notepad)
        menu.addAction("Save notepad as…", self.save_as)
        menu.exec(event.globalPos())

    # ── Show / hide / close ───────────────────────────────────────────────────

    def hideEvent(self, event) -> None:
        # /show-pet hides the pet: persist edits and come back collapsed.
        self.collapse()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._remember_size()
        if self._panel is not None:
            self._panel.flush_blocking()
        super().closeEvent(event)

    # ── Drag support ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        event.accept()

    # ── GIF cycling ───────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._movie is None:
            self._play_random()

    def _pick_random_index(self) -> int | None:
        n = len(self._gifs)
        if n == 0:
            return None
        if n == 1:
            return 0
        idx = random.randrange(n)
        while idx == self._last_index:
            idx = random.randrange(n)
        return idx

    def _play_random(self) -> None:
        idx = self._pick_random_index()
        if idx is None:
            self._label.setText("?")
            return
        self._last_index = idx
        self._play_gif(self._gifs[idx])

    def _play_gif(self, path: Path) -> None:
        self._clear_media()
        if not path.is_file():
            self._play_random()
            return
        natural = QImageReader(str(path)).size()
        movie = QMovie(str(path))
        movie.setParent(self)
        if not movie.isValid():
            movie.setParent(None)
            movie.deleteLater()
            self._play_random()
            return
        if natural.isValid() and not natural.isEmpty():
            scaled = natural.scaled(_PET_SIZE, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            scaled = _PET_SIZE
        movie.setScaledSize(scaled)
        movie.setSpeed(100)
        self._movie = movie
        self._seen_last_frame = False
        self._label.setMovie(movie)
        movie.frameChanged.connect(self._on_frame_changed)
        movie.start()

    def _on_frame_changed(self, frame_number: int) -> None:
        if self._movie is None:
            return
        last = self._movie.frameCount() - 1
        if last < 1:
            return
        if frame_number >= last:
            self._seen_last_frame = True
        elif self._seen_last_frame and frame_number == 0:
            self._play_random()

    def _clear_media(self) -> None:
        if self._movie is not None:
            self._movie.frameChanged.disconnect(self._on_frame_changed)
            self._movie.stop()
            self._movie.setParent(None)
            self._movie.deleteLater()
            self._movie = None
        self._label.clear()
