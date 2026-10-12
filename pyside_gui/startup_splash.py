from __future__ import annotations

import logging
import random
from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, QRect, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

_LOGGER = logging.getLogger(__name__)

_VIDEO_SUFFIXES = frozenset({".mp4", ".webm", ".mov", ".mkv", ".avi"})
_SCREEN_FRACTION = 0.55  # splash width as a share of the available screen width
_ASPECT = QSize(16, 9)  # until the video reports its own size
_FADE_MS = 450
_MAX_MS = 20_000  # never let a stuck or very long video hold the main window back
_VOLUME = 0.6


def pick_video(folder: Path) -> Path | None:
    """A random startup video from ``folder``, or ``None`` when there is none."""
    if not folder.is_dir():
        return None
    videos = sorted(p for p in folder.iterdir() if p.suffix.lower() in _VIDEO_SUFFIXES)
    return random.choice(videos) if videos else None


def splash_geometry(screen: QRect, aspect: QSize, fraction: float = _SCREEN_FRACTION) -> QRect:
    """Rect ``fraction`` of the screen wide at ``aspect``, centred and kept on screen."""
    width = round(screen.width() * fraction)
    height = round(width * aspect.height() / aspect.width())
    if height > screen.height() * fraction:
        height = round(screen.height() * fraction)
        width = round(height * aspect.width() / aspect.height())
    return QRect(
        screen.x() + (screen.width() - width) // 2,
        screen.y() + (screen.height() - height) // 2,
        width,
        height,
    )


class StartupSplash(QWidget):
    """Frameless window that plays one startup video, then fades out.

    ``fading`` fires once when the fade begins (show the main window then, so
    the splash cross-fades over it) and ``finished`` once it has closed. Any
    click or key skips straight to the fade; a decode error skips it too.
    """

    fading = Signal()
    finished = Signal()

    def __init__(self, video: Path) -> None:
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet("background: black;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click or press any key to skip")
        self._fade: QPropertyAnimation | None = None

        self._video = QVideoWidget(self)
        self._video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        # The video widget would otherwise swallow the clicks that skip the splash.
        self._video.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._video)

        self._audio = QAudioOutput(self)
        self._audio.setVolume(_VOLUME)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.positionChanged.connect(self._on_position)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(self._on_error)
        self._player.setSource(QUrl.fromLocalFile(str(video)))

        self._place(_ASPECT)
        self._player.videoSink().videoSizeChanged.connect(self._on_video_size)

    @classmethod
    def from_folder(cls, folder: Path) -> StartupSplash | None:
        video = pick_video(folder)
        return cls(video) if video else None

    def start(self) -> None:
        self.show()
        self.raise_()
        self._player.play()
        QTimer.singleShot(_MAX_MS, self.skip)

    @property
    def is_fading(self) -> bool:
        return self._fade is not None

    @Slot()
    def skip(self) -> None:
        """Begin the fade-out now (idempotent)."""
        if self._fade is not None:
            return
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(_FADE_MS)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._close)
        self.fading.emit()
        self.raise_()
        self._fade.start()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.skip()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self.skip()

    def _place(self, aspect: QSize) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(splash_geometry(screen.availableGeometry(), aspect))

    @Slot()
    def _on_video_size(self) -> None:
        size = self._player.videoSink().videoSize()
        if not size.isEmpty():
            self._place(size)

    @Slot(int)
    def _on_position(self, position: int) -> None:
        duration = self._player.duration()
        if duration > 0 and position >= duration - _FADE_MS:
            self.skip()  # fade over the last frames instead of a blank end

    @Slot(QMediaPlayer.MediaStatus)
    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            self.skip()

    @Slot(QMediaPlayer.Error, str)
    def _on_error(self, error: QMediaPlayer.Error, message: str) -> None:
        _LOGGER.warning("startup video failed: %s", message)
        self.skip()

    @Slot()
    def _close(self) -> None:
        self._player.stop()
        self.close()
        self.finished.emit()
