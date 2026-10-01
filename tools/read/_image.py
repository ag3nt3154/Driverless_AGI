"""tools/read/_image.py — Load an image file as an attachment for the LLM.

PNG/JPEG within limits pass through byte-for-byte. Other formats (GIF, WebP,
BMP — first frame only) and oversized images are re-encoded: downscaled to
``max_pixels``, then PNG, then JPEG if the PNG is still over ``max_bytes``.
"""
from __future__ import annotations

import io
from pathlib import Path

from agent.user_input import ImageAttachment
from tools.read._convert import CANNOT_PROCESS

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_PASSTHROUGH = {"PNG": "image/png", "JPEG": "image/jpeg"}


class ImageLoadError(Exception):
    """str(exc) is the agent-facing message."""


def load_image(path: Path, *, max_bytes: int, max_pixels: int) -> ImageAttachment:
    try:
        from PIL import Image
    except ImportError:
        raise ImageLoadError(
            f"Error ({CANNOT_PROCESS}): Cannot read image '{path.name}': Pillow is not installed."
        )

    data = path.read_bytes()
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ImageLoadError(
            f"Error ({CANNOT_PROCESS}): '{path.name}' is not a readable image: {exc}"
        )

    width, height = img.size
    mime = _PASSTHROUGH.get(img.format or "")
    if mime and len(data) <= max_bytes and width * height <= max_pixels:
        return ImageAttachment(data=data, mime_type=mime, width=width, height=height, name=path.name)

    if width * height > max_pixels:
        scale = (max_pixels / (width * height)) ** 0.5
        img = img.resize((max(1, int(width * scale)), max(1, int(height * scale))))
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    mime = "image/png"
    if buf.tell() > max_bytes:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        mime = "image/jpeg"
    if buf.tell() > max_bytes:
        raise ImageLoadError(
            f"Error ({CANNOT_PROCESS}): '{path.name}' is still {buf.tell()} bytes after "
            f"re-encoding, over the {max_bytes}-byte image limit."
        )
    return ImageAttachment(
        data=buf.getvalue(), mime_type=mime,
        width=img.size[0], height=img.size[1], name=path.name,
    )
