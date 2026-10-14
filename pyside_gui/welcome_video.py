"""Idle videos for the empty-chat welcome screen.

QtWebEngine ships without H.264, so the conversation page cannot play the .mp4
emotes itself. Qt Multimedia decodes them here and each frame reaches the page
as a small JPEG data URL.
"""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame, QVideoSink

from pyside_gui.startup_splash import _VIDEO_SUFFIXES

_LOGGER = logging.getLogger(__name__)

_FRAME_PX = 600  # longest side sent to the page: the 300px welcome image at 2x DPI
_MIN_FRAME_S = 1 / 30
_JPEG_QUALITY = 80


def idle_videos(folder: Path) -> list[Path]:
    """The videos in ``folder``, in name order; empty when there are none."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in _VIDEO_SUFFIXES)


def frame_data_url(frame: QVideoFrame, max_px: int = _FRAME_PX) -> str | None:
    image = frame.toImage()
    if image.isNull():
        return None
    if max(image.width(), image.height()) > max_px:
        image = image.scaled(
            max_px, max_px,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPEG", _JPEG_QUALITY)
    return "data:image/jpeg;base64," + bytes(data.toBase64()).decode("ascii")


class WelcomeVideo(QObject):
    """Plays ``videos`` muted, one after another on a loop, emitting each frame.

    Starts at a random video so each welcome screen differs. Frames are capped
    at 30 per second; a file that fails to decode is skipped.
    """

    frame = Signal(str)  # data:image/jpeg;base64,...

    def __init__(self, videos: list[Path], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._videos = list(videos)
        self._index = random.randrange(len(self._videos)) if self._videos else 0
        self._last_frame = 0.0
        self._failures = 0
        self._player = QMediaPlayer(self)
        if len(self._videos) == 1:
            self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._player.setVideoSink(self._sink)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(self._on_error)

    @property
    def active(self) -> bool:
        return self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState

    def start(self) -> None:
        if not self._videos:
            return
        self._failures = 0
        self._load(self._index)
        self._player.play()

    def stop(self) -> None:
        self._player.stop()

    def pause(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()

    def resume(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()

    def _load(self, index: int) -> None:
        self._index = index % len(self._videos)
        self._player.setSource(QUrl.fromLocalFile(str(self._videos[self._index])))

    def _advance(self) -> None:
        self._load(self._index + 1)
        self._player.play()

    @Slot(QVideoFrame)
    def _on_frame(self, frame: QVideoFrame) -> None:
        now = time.monotonic()
        if now - self._last_frame < _MIN_FRAME_S:
            return
        url = frame_data_url(frame)
        if url:
            self._last_frame = now
            self._failures = 0
            self.frame.emit(url)

    @Slot(QMediaPlayer.MediaStatus)
    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia and len(self._videos) > 1:
            self._advance()

    @Slot(QMediaPlayer.Error, str)
    def _on_error(self, error: QMediaPlayer.Error, message: str) -> None:
        _LOGGER.warning("welcome video %s failed: %s", self._videos[self._index].name, message)
        self._failures += 1
        if self._failures < len(self._videos):
            self._advance()
        else:
            self.stop()
