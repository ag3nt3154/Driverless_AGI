from __future__ import annotations

import sys
from pathlib import Path

import pyside_gui  # noqa: F401 - must be imported before any PySide6 import

from PySide6.QtGui import QColor, QImage, QMovie
from PySide6.QtWidgets import QApplication, QLabel

from agent.expression_assets import ImageAsset, TextFallback
from agent.process_state import ProcessSnapshot
from pyside_gui.expression_widget import ExpressionWidget
from pyside_gui.right_sidebar import RightSidebar

_app = QApplication.instance() or QApplication(sys.argv)

_GIF_1PX = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


def _emotes_root(tmp_path: Path, default: str = "default") -> Path:
    root = tmp_path / "emotes"
    root.mkdir()
    (root / "default.md").write_text(default, encoding="utf-8")
    return root


def _fallback(path: Path, text: str) -> TextFallback:
    path.write_text(text, encoding="utf-8")
    return TextFallback(path=path, reason="test", text=text)


def _image_label(widget: ExpressionWidget) -> QLabel:
    label = widget.findChild(QLabel, "expression-image")
    assert label is not None
    return label


def _caption_label(widget: ExpressionWidget) -> QLabel:
    label = widget.findChild(QLabel, "expression-caption")
    assert label is not None
    return label


def test_initial_state_is_idle_with_default_fallback(tmp_path: Path) -> None:
    widget = ExpressionWidget(_emotes_root(tmp_path))

    assert _image_label(widget).text() == "default"
    assert _caption_label(widget).text() == "PROCESS idle"


def test_update_process_renders_asset_and_caption(tmp_path: Path) -> None:
    widget = ExpressionWidget(_emotes_root(tmp_path))

    widget.update_process(
        ProcessSnapshot("tool:bash", _fallback(tmp_path / "process.md", "PROCESS  text\n"))
    )
    _app.processEvents()

    assert _image_label(widget).text() == "PROCESS  text\n"
    assert _caption_label(widget).text() == "PROCESS tool:bash"

    widget.update_process(ProcessSnapshot("thinking", _fallback(tmp_path / "new.md", "NEW")))

    assert _image_label(widget).text() == "NEW"
    assert _caption_label(widget).text() == "PROCESS thinking"


def test_invalid_image_asset_uses_default_text_with_monospace_font(
    tmp_path: Path,
) -> None:
    expected = "  keep\tthis\nline  two\n"
    root = _emotes_root(tmp_path, expected)
    widget = ExpressionWidget(root)

    widget.update_process(ProcessSnapshot("tool:read", ImageAsset("missing", root / "missing.png")))
    _app.processEvents()

    label = _image_label(widget)
    assert label.text() == expected
    assert label.font().fixedPitch()


def test_static_images_are_scaled_with_aspect_ratio(tmp_path: Path) -> None:
    root = _emotes_root(tmp_path)
    image_path = root / "wide.png"
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("#89b4fa"))
    assert image.save(str(image_path), "PNG")
    widget = ExpressionWidget(root)
    widget.resize(180, 180)

    widget.update_process(ProcessSnapshot("thinking", ImageAsset("wide", image_path)))
    _app.processEvents()

    pixmap = _image_label(widget).pixmap()
    assert pixmap is not None
    assert pixmap.width() > pixmap.height()
    assert round(pixmap.width() / pixmap.height(), 1) == 2.0


def test_gif_plays_and_is_released_when_state_changes(tmp_path: Path) -> None:
    root = _emotes_root(tmp_path)
    gif_path = root / "idle.gif"
    gif_path.write_bytes(_GIF_1PX)
    widget = ExpressionWidget(root)

    widget.update_process(ProcessSnapshot("thinking", ImageAsset("idle", gif_path)))
    _app.processEvents()
    movie = widget._movie

    assert movie is not None
    assert movie.state() == QMovie.MovieState.Running
    assert _image_label(widget).movie() is movie

    widget.update_process(
        ProcessSnapshot("idle", _fallback(tmp_path / "fallback.md", "fallback"))
    )
    _app.processEvents()

    assert widget._movie is None
    assert _image_label(widget).text() == "fallback"


def test_invalid_media_decode_warns_once_per_operation_and_path(
    tmp_path: Path,
    caplog,
) -> None:
    root = _emotes_root(tmp_path)
    bad_png = root / "bad.png"
    bad_png.write_bytes(b"not a png")
    widget = ExpressionWidget(root)

    with caplog.at_level("WARNING", logger="pyside_gui.expression_widget"):
        widget.update_process(ProcessSnapshot("tool:bad", ImageAsset("bad", bad_png)))
        widget.update_process(ProcessSnapshot("tool:bad", ImageAsset("bad", bad_png)))
        widget.update_process(ProcessSnapshot("tool:bad", ImageAsset("missing", root / "gone.png")))
        _app.processEvents()

    matching = [message for message in caplog.messages if str(bad_png) in message]
    assert matching == [f"process pixmap decode failed: {bad_png}"]
    assert any("process pixmap missing" in message for message in caplog.messages)
    assert _image_label(widget).text() == "default"


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
