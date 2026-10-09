from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from pyside_gui.image_preview import check_image_limits, read_preview


def _png(tmp_path, width, height):
    path = tmp_path / "image.png"
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0x123456)
    assert image.save(str(path))
    return path


def test_small_image_is_not_upscaled(tmp_path):
    image, error = read_preview(_png(tmp_path, 4, 4), QSize(400, 400))
    assert error is None
    assert image.size() == QSize(4, 4)


def test_large_image_is_downscaled_keeping_aspect(tmp_path):
    image, error = read_preview(_png(tmp_path, 200, 100), QSize(50, 50))
    assert error is None
    assert image.size() == QSize(50, 25)


def test_check_image_limits_rejects_oversized_bytes_and_missing(tmp_path, monkeypatch):
    path = _png(tmp_path, 4, 4)
    assert check_image_limits(path) is None
    assert "Cannot display image" in check_image_limits(tmp_path / "missing.png")
    monkeypatch.setattr("pyside_gui.image_preview.MAX_IMAGE_PIXELS", 15)
    assert "dimensions" in check_image_limits(path)
    monkeypatch.setattr("pyside_gui.image_preview.MAX_IMAGE_BYTES", 1)
    assert "too large" in check_image_limits(path)
