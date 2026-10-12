from __future__ import annotations

from PySide6.QtCore import QRect, QSize

from pyside_gui.startup_splash import StartupSplash, pick_video, splash_geometry


def test_pick_video_ignores_other_files(tmp_path):
    assert pick_video(tmp_path / "missing") is None
    (tmp_path / "notes.md").write_text("x")
    assert pick_video(tmp_path) is None
    (tmp_path / "intro.MP4").write_bytes(b"")
    assert pick_video(tmp_path) == tmp_path / "intro.MP4"


def test_splash_geometry_is_centred_at_aspect():
    rect = splash_geometry(QRect(0, 0, 2000, 1200), QSize(16, 9), 0.5)
    assert rect == QRect(500, 319, 1000, 562)


def test_splash_geometry_limited_by_height_on_tall_aspect():
    rect = splash_geometry(QRect(100, 0, 2000, 1000), QSize(1, 2), 0.5)
    assert (rect.width(), rect.height()) == (250, 500)
    assert rect.center().x() == 1099


def test_skip_fades_once_then_finishes(qtbot, tmp_path):
    splash = StartupSplash(tmp_path / "none.mp4")
    fades: list[None] = []
    splash.fading.connect(lambda: fades.append(None))
    with qtbot.waitSignal(splash.finished, timeout=3000):
        splash.skip()
        splash.skip()
        assert splash.is_fading
    assert len(fades) == 1


def test_unplayable_video_skips_itself(qtbot, tmp_path):
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"not a video")
    splash = StartupSplash(bad)
    with qtbot.waitSignal(splash.finished, timeout=5000):
        splash.start()
