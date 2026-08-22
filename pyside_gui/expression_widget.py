from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Slot
from PySide6.QtGui import QFont, QMovie, QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from agent.affect import AffectSnapshot, AffectVector
from agent.expression_assets import AssetRef, ImageAsset, TextFallback, load_fallback
from agent.process_state import ProcessSnapshot


class ExpressionWidget(QWidget):
    """Renders alternating affect and process-state expression channels."""

    def __init__(
        self,
        emotes_root: Path,
        *,
        rotation_interval_ms: int = 3000,
    ) -> None:
        super().__init__()
        self._emotes_root = emotes_root
        self._default_fallback = load_fallback(emotes_root)
        self._channel = "vad"
        self._movie: QMovie | None = None
        self._static_pixmap: QPixmap | None = None
        self._affect_snapshot = self._initial_affect()
        self._process_snapshot = ProcessSnapshot("idle", self._default_fallback)

        self._image_label = QLabel()
        self._image_label.setObjectName("expression-image")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setTextFormat(Qt.TextFormat.PlainText)
        self._image_label.setWordWrap(False)
        self._image_label.setMinimumHeight(96)

        self._caption_label = QLabel()
        self._caption_label.setObjectName("expression-caption")
        self._caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(4)
        layout.addWidget(self._image_label)
        layout.addWidget(self._caption_label)

        self._rotation_timer = QTimer(self)
        self._rotation_timer.setInterval(rotation_interval_ms)
        self._rotation_timer.timeout.connect(self._rotate_channel)
        self._rotation_timer.start()
        self._render_current()

    @Slot(object)
    def update_affect(self, snapshot: AffectSnapshot) -> None:
        self._affect_snapshot = snapshot
        if self._channel == "vad":
            self._render_current()

    @Slot(object)
    def update_process(self, snapshot: ProcessSnapshot) -> None:
        self._process_snapshot = snapshot
        if self._channel == "process":
            self._render_current()

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

    def _render_current(self) -> None:
        if self._channel == "process":
            snapshot = self._process_snapshot
            self._render_asset(snapshot.asset)
            self._caption_label.setText(f"PROCESS {snapshot.state}")
            return
        snapshot = self._affect_snapshot
        current = snapshot.current
        self._render_asset(snapshot.asset)
        self._caption_label.setText(
            f"VAD {snapshot.emote_id} | V={current.valence:+.2f} "
            f"A={current.arousal:+.2f} D={current.dominance:+.2f}"
        )

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

    def _show_movie(self, asset: ImageAsset) -> bool:
        self._clear_media()
        if not asset.path.is_file():
            return False
        movie = QMovie(str(asset.path))
        movie.setParent(self)
        if not movie.isValid():
            movie.stop()
            return False
        movie.setScaledSize(self._target_size())
        self._movie = movie
        self._image_label.setMovie(movie)
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
        self._image_label.setPixmap(self._scaled_pixmap())
        return True

    def _clear_media(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
        self._static_pixmap = None
        self._image_label.clear()

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
        height = size.height() if size.height() > 0 else 140
        return QSize(max(width, 1), max(height, 1))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._movie is not None:
            self._movie.setScaledSize(self._target_size())
        if self._static_pixmap is not None:
            self._image_label.setPixmap(self._scaled_pixmap())
