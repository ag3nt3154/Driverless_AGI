from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Slot
from PySide6.QtGui import QFont, QImageReader, QMovie, QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from agent.affect import AffectSnapshot, AffectVector
from agent.expression_assets import AssetRef, ImageAsset, TextFallback, load_fallback
from agent.process_state import ProcessSnapshot

_LOGGER = logging.getLogger(__name__)


class ExpressionWidget(QWidget):
    """Renders alternating affect and process-state expression channels."""

    def __init__(
        self,
        emotes_root: Path,
    ) -> None:
        super().__init__()
        self._emotes_root = emotes_root
        self._default_fallback = load_fallback(emotes_root)
        self._channel = "vad"
        self._movie: QMovie | None = None
        self._movie_natural_size: QSize | None = None
        self._static_pixmap: QPixmap | None = None
        self._warned_media_failures: set[str] = set()
        self._affect_snapshot = self._initial_affect()
        self._process_snapshot = ProcessSnapshot("idle", self._default_fallback)

        self._image_label = QLabel()
        self._image_label.setObjectName("expression-image")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setTextFormat(Qt.TextFormat.PlainText)
        self._image_label.setWordWrap(False)
        self._image_label.setMinimumHeight(80)
        self._image_label.setMaximumHeight(260)
        self._image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self._caption_label = QLabel()
        self._caption_label.setObjectName("expression-caption")
        self._caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(4)
        layout.addWidget(self._image_label)
        layout.addWidget(self._caption_label)

        self._rotation_timer = QTimer(self)
        self._rotation_timer.setSingleShot(True)
        self._rotation_timer.timeout.connect(self._rotate_channel)
        self._render_current()

    @Slot(object)
    def update_affect(self, snapshot: AffectSnapshot) -> None:
        self._affect_snapshot = snapshot
        if self._channel == "vad":
            self._update_caption()

    @Slot(object)
    def update_process(self, snapshot: ProcessSnapshot) -> None:
        self._process_snapshot = snapshot
        if self._channel == "process":
            self._update_caption()

    def _initial_affect(self) -> AffectSnapshot:
        zero = AffectVector(0.0, 0.0, 0.0)
        return AffectSnapshot(
            baseline=zero,
            current=zero,
            emote_id="default",
            asset=self._default_fallback,
            reason="init",
        )

    def _rotate_channel(self) -> None:
        self._channel = "process" if self._channel == "vad" else "vad"
        self._render_current()

    def _update_caption(self) -> None:
        if self._channel == "process":
            self._caption_label.setText(f"PROCESS {self._process_snapshot.state}")
        else:
            current = self._affect_snapshot.current
            self._caption_label.setText(
                f"V={current.valence:+.2f} A={current.arousal:+.2f} D={current.dominance:+.2f}"
            )

    def _render_current(self) -> None:
        if self._channel == "process":
            self._render_asset(self._process_snapshot.asset)
        else:
            self._render_asset(self._affect_snapshot.asset)
        self._update_caption()

    def _render_asset(self, asset: AssetRef) -> None:
        if isinstance(asset, TextFallback):
            self._show_text(asset.text)
            return
        if asset.path.suffix.lower() == ".gif":
            if self._show_movie(asset):
                return
        elif self._show_pixmap(asset):
            return
        self._show_text(self._default_fallback.text)

    def _show_text(self, text: str) -> None:
        self._clear_media()
        font = QFont("Cascadia Code")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self._image_label.setFont(font)
        self._image_label.setText(text)
        self._rotation_timer.start(5000)

    def _show_movie(self, asset: ImageAsset) -> bool:
        self._clear_media()
        if not asset.path.is_file():
            self._warn_media_failure("gif missing", asset.path)
            return False
        natural = QImageReader(str(asset.path)).size()
        self._movie_natural_size = natural if natural.isValid() and not natural.isEmpty() else None
        movie = QMovie(str(asset.path))
        movie.setParent(self)
        if not movie.isValid():
            self._warn_media_failure("gif decode failed", asset.path)
            self._release_movie(movie)
            self._movie_natural_size = None
            return False
        movie.setScaledSize(self._movie_scaled_size())
        self._movie = movie
        self._image_label.setMovie(movie)
        movie.start()
        frame_count = movie.frameCount()
        if frame_count > 0:
            def _on_frame(n: int, _fc: int = frame_count, _m: QMovie = movie) -> None:
                if n == _fc - 1:
                    _m.stop()
                    QTimer.singleShot(0, self._rotate_channel)
            movie.frameChanged.connect(_on_frame)
        else:
            self._rotation_timer.start(5000)
        return True

    def _show_pixmap(self, asset: ImageAsset) -> bool:
        self._clear_media()
        if not asset.path.is_file():
            self._warn_media_failure("pixmap missing", asset.path)
            return False
        pixmap = QPixmap(str(asset.path))
        if pixmap.isNull():
            self._warn_media_failure("pixmap decode failed", asset.path)
            return False
        self._static_pixmap = pixmap
        self._image_label.setPixmap(self._scaled_pixmap())
        self._rotation_timer.start(5000)
        return True

    def _clear_media(self) -> None:
        self._rotation_timer.stop()
        if self._movie is not None:
            self._release_movie(self._movie)
            self._movie = None
        self._movie_natural_size = None
        self._static_pixmap = None
        self._image_label.clear()

    def _release_movie(self, movie: QMovie) -> None:
        movie.stop()
        movie.setParent(None)
        movie.deleteLater()

    def _warn_media_failure(self, operation: str, path: Path) -> None:
        key = f"{self._channel}:{operation}:{path}"
        if key in self._warned_media_failures:
            return
        self._warned_media_failures.add(key)
        _LOGGER.warning("%s %s: %s", self._channel, operation, path)

    def _scaled_pixmap(self) -> QPixmap:
        if self._static_pixmap is None:
            return QPixmap()
        return self._static_pixmap.scaled(
            self._target_size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _target_size(self) -> QSize:
        size = self._image_label.size()
        width = size.width() if size.width() > 0 else max(self.width(), 160)
        height = min(size.height() if size.height() > 0 else 260, 260)
        return QSize(max(width, 1), max(height, 1))

    _GIF_BOUND = QSize(300, 260)

    def _movie_scaled_size(self) -> QSize:
        if self._movie_natural_size is not None:
            return self._movie_natural_size.scaled(
                self._GIF_BOUND, Qt.AspectRatioMode.KeepAspectRatio
            )
        return self._GIF_BOUND

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._static_pixmap is not None:
            self._image_label.setPixmap(self._scaled_pixmap())
