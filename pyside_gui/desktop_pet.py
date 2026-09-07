from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, Slot
from PySide6.QtGui import QImageReader, QMovie, QMouseEvent, QPixmap, QScreen
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from agent.expression import ExpressionSnapshot
from agent.expression_assets import AssetRef, ImageAsset, TextFallback

_LOGGER = logging.getLogger(__name__)

_PET_SIZE = QSize(210, 182)  # same as ExpressionWidget._GIF_BOUND
_EDGE_INSET = 20


class DesktopPetWindow(QWidget):
    """Frameless always-on-top window that displays VAD expression emotes."""

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
        self._static_pixmap: QPixmap | None = None

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

    # ── Expression rendering ──────────────────────────────────────────────────

    @Slot(object)
    def update_expression(self, snapshot: ExpressionSnapshot) -> None:
        self._render_asset(snapshot.asset)

    def _render_asset(self, asset: AssetRef) -> None:
        if isinstance(asset, TextFallback):
            self._clear_media()
            self._label.setText(asset.text)
            return
        if asset.path.suffix.lower() == ".gif":
            if self._show_movie(asset):
                return
        elif self._show_pixmap(asset):
            return
        self._clear_media()
        self._label.setText("?")

    def _show_movie(self, asset: ImageAsset) -> bool:
        self._clear_media()
        if not asset.path.is_file():
            return False
        natural = QImageReader(str(asset.path)).size()
        movie = QMovie(str(asset.path))
        movie.setParent(self)
        if not movie.isValid():
            movie.setParent(None)
            movie.deleteLater()
            return False
        if natural.isValid() and not natural.isEmpty():
            scaled = natural.scaled(_PET_SIZE, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            scaled = _PET_SIZE
        movie.setScaledSize(scaled)
        self._movie = movie
        self._label.setMovie(movie)
        movie.start()
        return True

    def _show_pixmap(self, asset: ImageAsset) -> bool:
        self._clear_media()
        if not asset.path.is_file():
            return False
        pixmap = QPixmap(str(asset.path))
        if pixmap.isNull():
            return False
        self._static_pixmap = pixmap
        self._label.setPixmap(
            pixmap.scaled(
                _PET_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        return True

    def _clear_media(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.setParent(None)
            self._movie.deleteLater()
            self._movie = None
        self._static_pixmap = None
        self._label.clear()
