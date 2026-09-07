from __future__ import annotations

import logging
import random
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, Slot
from PySide6.QtGui import QImageReader, QMovie, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from agent import DAGI_ROOT

_LOGGER = logging.getLogger(__name__)

_PET_SIZE = QSize(210, 182)
_EDGE_INSET = 20
_GIF_SUFFIXES = frozenset({".gif"})


def _scan_gifs(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in _GIF_SUFFIXES)


class DesktopPetWindow(QWidget):
    """Frameless always-on-top window that randomly cycles through VAD emote GIFs."""

    def __init__(self) -> None:
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setFixedSize(_PET_SIZE)
        layout.addWidget(self._label)

        self._move_to_default()

    def _move_to_default(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.right() - _PET_SIZE.width() - _EDGE_INSET
        y = geo.bottom() - _PET_SIZE.height() - _EDGE_INSET
        self.move(x, y)

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
