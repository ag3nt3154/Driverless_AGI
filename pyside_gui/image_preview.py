"""Bounded Qt image decoding shared by board cards and the file viewer."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000


def check_image_limits(path: Path) -> str | None:
    """Return why an image must not be decoded, or None when it is within limits."""
    try:
        byte_size = path.stat().st_size
    except OSError as error:
        return f"Cannot display image: {error}"
    if not 1 <= byte_size <= MAX_IMAGE_BYTES:
        return f"Image too large to display ({byte_size:,} bytes)"
    dimensions = QImageReader(str(path)).size()
    pixels = dimensions.width() * dimensions.height()
    if not dimensions.isValid() or pixels <= 0 or pixels > MAX_IMAGE_PIXELS:
        return "Cannot display image: invalid or excessive dimensions"
    return None


def read_preview(path: Path, target: QSize) -> tuple[QImage | None, str | None]:
    error = check_image_limits(path)
    if error is not None:
        return None, error
    reader = QImageReader(str(path))
    dimensions = reader.size()
    if dimensions.width() > target.width() or dimensions.height() > target.height():
        reader.setScaledSize(dimensions.scaled(target, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        return None, f"Cannot display image: {reader.errorString()}"
    return image, None
