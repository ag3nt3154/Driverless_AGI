from __future__ import annotations

import sys
from pathlib import Path

import pyside_gui  # noqa: F401 - must be imported before any PySide6 import

from PySide6.QtGui import QColor, QImage, QMovie
from PySide6.QtWidgets import QApplication, QLabel

from agent.expression import ExpressionSnapshot
from agent.expression_assets import ImageAsset, TextFallback
from agent.process_state import ProcessSnapshot
from pyside_gui.expression_widget import ExpressionWidget
from pyside_gui.right_sidebar import RightSidebar

_app = QApplication.instance() or QApplication(sys.argv)


def _fallback(path: Path, text: str) -> TextFallback:
    path.write_text(text, encoding="utf-8")
    return TextFallback(path=path, reason="test", text=text)


def _expression(asset, emote_id: str = "focused") -> ExpressionSnapshot:
    return ExpressionSnapshot(emote_id, asset)


def _image_label(widget: ExpressionWidget) -> QLabel:
    label = widget.findChild(QLabel, "expression-image")
    assert label is not None
    return label


def _caption_label(widget: ExpressionWidget) -> QLabel:
    label = widget.findChild(QLabel, "expression-caption")
    assert label is not None
    return label


def test_updates_keep_expression_until_timer_rotates(tmp_path: Path) -> None:
    root = tmp_path / "emotes"
    root.mkdir()
    (root / "default.md").write_text("default", encoding="utf-8")
    affect_asset = _fallback(tmp_path / "affect.md", "AFFECT  text\n")
    process_asset = _fallback(tmp_path / "process.md", "PROCESS text")
    widget = ExpressionWidget(root)

    widget.update_expression(_expression(affect_asset))
    widget.update_process(ProcessSnapshot("tool:bash", process_asset))
    _app.processEvents()

    assert widget._rotation_timer.isActive()
    assert widget._rotation_timer.interval() == 5000
    assert _image_label(widget).text() == "AFFECT  text\n"
    assert _caption_label(widget).text() == "PROCESS tool:bash"

    widget._rotate_channel()

    assert _image_label(widget).text() == "PROCESS text"
    assert _caption_label(widget).text() == "PROCESS tool:bash"

    widget.update_expression(_expression(_fallback(tmp_path / "new.md", "NEW"), "new"))

    assert _image_label(widget).text() == "PROCESS text"
    assert _caption_label(widget).text() == "PROCESS tool:bash"

    widget._rotate_channel()

    assert _image_label(widget).text() == "NEW"
    assert _caption_label(widget).text() == "PROCESS tool:bash"


def test_initial_rotation_has_idle_process_channel(tmp_path: Path) -> None:
    root = tmp_path / "emotes"
    root.mkdir()
    (root / "default.md").write_text("default", encoding="utf-8")
    widget = ExpressionWidget(root)

    assert _caption_label(widget).text() == "PROCESS idle"

    widget._rotate_channel()

    assert _image_label(widget).text() == "default"
    assert _caption_label(widget).text() == "PROCESS idle"


def test_invalid_image_asset_uses_default_text_with_monospace_font(
    tmp_path: Path,
) -> None:
    root = tmp_path / "emotes"
    root.mkdir()
    expected = "  keep\tthis\nline  two\n"
    (root / "default.md").write_text(expected, encoding="utf-8")
    widget = ExpressionWidget(root)

    widget.update_expression(_expression(ImageAsset("missing", root / "missing.png")))
    _app.processEvents()

    label = _image_label(widget)
    assert label.text() == expected
    assert label.font().fixedPitch()


def test_static_images_are_scaled_with_aspect_ratio(tmp_path: Path) -> None:
    root = tmp_path / "emotes"
    root.mkdir()
    (root / "default.md").write_text("default", encoding="utf-8")
    image_path = root / "wide.png"
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("#89b4fa"))
    assert image.save(str(image_path), "PNG")
    widget = ExpressionWidget(root)
    widget.resize(180, 180)

    widget.update_expression(_expression(ImageAsset("wide", image_path)))
    _app.processEvents()

    pixmap = _image_label(widget).pixmap()
    assert pixmap is not None
    assert pixmap.width() > pixmap.height()
    assert round(pixmap.width() / pixmap.height(), 1) == 2.0


def test_gif_keeps_playing_when_new_expression_arrives(tmp_path: Path) -> None:
    root = tmp_path / "emotes"
    root.mkdir()
    (root / "default.md").write_text("default", encoding="utf-8")
    gif_path = root / "idle.gif"
    gif_path.write_bytes(
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
        b"\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
        b"\x00\x02\x02D\x01\x00;"
    )
    widget = ExpressionWidget(root)

    widget.update_expression(_expression(ImageAsset("idle", gif_path)))
    _app.processEvents()
    movie = widget._movie

    assert movie is not None
    assert movie.state() == QMovie.MovieState.Running

    widget.update_expression(_expression(_fallback(tmp_path / "fallback.md", "fallback")))
    _app.processEvents()

    assert movie.state() == QMovie.MovieState.Running
    assert widget._movie is movie


def test_invalid_media_decode_warns_once_per_channel_operation_and_path(
    tmp_path: Path,
    caplog,
) -> None:
    root = tmp_path / "emotes"
    root.mkdir()
    (root / "default.md").write_text("default", encoding="utf-8")
    bad_png = root / "bad.png"
    bad_png.write_bytes(b"not a png")
    widget = ExpressionWidget(root)

    with caplog.at_level("WARNING", logger="pyside_gui.expression_widget"):
        widget.update_expression(_expression(ImageAsset("bad", bad_png)))
        widget.update_expression(_expression(ImageAsset("bad", bad_png)))
        widget._rotate_channel()
        widget.update_process(ProcessSnapshot("tool:bad", ImageAsset("bad", bad_png)))
        _app.processEvents()

    matching = [message for message in caplog.messages if str(bad_png) in message]
    assert len(matching) == 2
    assert any("expression pixmap decode failed" in message for message in matching)
    assert any("process pixmap decode failed" in message for message in matching)


def test_right_sidebar_preserves_sections_with_expression_widget(
    tmp_path: Path,
) -> None:
    dagi_root = tmp_path / "dagi"
    emotes_root = dagi_root / ".dagi" / "emotes"
    emotes_root.mkdir(parents=True)
    (emotes_root / "default.md").write_text("default", encoding="utf-8")

    sidebar = RightSidebar(
        "test-model",
        80_000,
        4_096,
        dagi_root,
        tmp_path,
    )

    assert sidebar.expression_widget.findChild(QLabel, "expression-image") is not None
    assert sidebar.findChild(QLabel, "status-label") is not None
    assert sidebar.findChild(QLabel, "model-label").text() == "test-model"
    headers = [label.text() for label in sidebar.findChildren(QLabel, "section-header")]
    assert headers == ["TOKENS", "CONTEXT"]
