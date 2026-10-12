from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyside_gui  # noqa: F401  (PySide6 DLL bootstrap before any PySide6 import)
from PySide6.QtWidgets import QApplication

from pyside_gui.startup_splash import StartupSplash


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def splash(qt_app, tmp_path: Path):
    widget = StartupSplash(tmp_path / "intro.mp4")
    # The fake file makes the player fail at once; keep that from skipping the splash.
    widget._player.errorOccurred.disconnect(widget._on_error)
    widget._player.mediaStatusChanged.disconnect(widget._on_status)
    yield widget
    widget._player.stop()
    widget.deleteLater()


class TestFirstFrameReveal:
    """The splash must never show as an empty black box before the video paints."""

    def test_start_keeps_splash_invisible_until_a_frame_arrives(self, splash):
        splash.start()
        assert splash.windowOpacity() == 0.0
        assert not splash.is_fading

    def test_first_frame_reveals_splash(self, splash):
        splash.start()
        splash._on_first_frame()
        assert splash.windowOpacity() == 1.0

    def test_no_frame_in_time_skips_splash(self, splash):
        fading: list[bool] = []
        splash.fading.connect(lambda: fading.append(True))
        splash.start()
        splash._on_no_frame()
        assert splash.is_fading
        assert fading == [True]

    def test_frame_before_timeout_keeps_playing(self, splash):
        splash.start()
        splash._on_first_frame()
        splash._on_no_frame()
        assert not splash.is_fading
