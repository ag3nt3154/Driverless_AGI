"""rpa/screen.py — screenshots and the set-of-marks overlay (D4, S0).

Labels must sit inside each box's top-left corner (never in the gap between
controls); only interactive leaf elements with area > 0 are marked. See S0
"Live vision check" in research.md for why.
"""
from __future__ import annotations

import io
from typing import Callable, Sequence

from PIL import Image, ImageDraw, ImageFont

from rpa.model import Element

_BOX_COLOR = (255, 0, 0)
_BOX_WIDTH = 2
_LEADER_WIDTH = 1
_FONT_SIZE = 13


def capture_window(
    window_rect_screen: tuple[int, int, int, int],
    region: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    """Capture the window at `window_rect_screen` (left, top, right, bottom) in
    screen coordinates. `region` is (left, top, right, bottom) relative to the
    window; when given, only that sub-area is captured.
    """
    import mss

    left, top, right, bottom = window_rect_screen
    if region is not None:
        rl, rt, rr, rb = region
        left, top, right, bottom = left + rl, top + rt, left + rr, top + rb
    monitor = {
        "left": left,
        "top": top,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
    }
    with mss.MSS() as sct:
        shot = sct.grab(monitor)
    return Image.frombytes("RGB", shot.size, shot.rgb)


def _load_font() -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arialbd.ttf", _FONT_SIZE)
    except OSError:
        return ImageFont.load_default()


def _tag_size(font: ImageFont.ImageFont, text: str) -> tuple[int, int]:
    bbox = font.getbbox(text)
    w = bbox[2] - bbox[0] + 6
    h = bbox[3] - bbox[1] + 4
    return w, h


def _estimate_tag_size(text: str, font_size: int = _FONT_SIZE) -> tuple[int, int]:
    """Font-file-free tag size (fixed-width estimate) for pure layout tests."""
    return max(1, round(font_size * 0.6)) * len(text) + 6, round(font_size * 1.2) + 4


Rect = tuple[int, int, int, int]


def marks_layout(
    elements: Sequence[Element],
    image_size: tuple[int, int],
    *,
    offset: tuple[int, int] = (0, 0),
    measure: Callable[[str], tuple[int, int]] = _estimate_tag_size,
) -> list[tuple[int, Rect, Rect]]:
    """(index, tag_rect, box_rect) in image coordinates for every interactive,
    non-zero-area element. The tag sits inside the box's top-left corner; if the
    box is smaller than the tag it goes to the left of the box (top-aligned), or
    to the right when the left side would leave the image. `offset` is subtracted
    from every bbox (for crops). `measure(text) -> (w, h)` sizes the tag.
    """
    img_w, _ = image_size
    ox, oy = offset
    layout: list[tuple[int, Rect, Rect]] = []
    for el in elements:
        if not el.interactive:
            continue
        left, top, right, bottom = el.bbox
        left, top, right, bottom = left - ox, top - oy, right - ox, bottom - oy
        if right - left <= 0 or bottom - top <= 0:
            continue
        tag_w, tag_h = measure(str(el.index))
        if right - left >= tag_w and bottom - top >= tag_h:
            tag_left = left
        elif left - tag_w >= 0 or right + tag_w > img_w:
            tag_left = left - tag_w
        else:
            tag_left = right
        layout.append((el.index, (tag_left, top, tag_left + tag_w, top + tag_h), (left, top, right, bottom)))
    return layout


def mark(
    image: Image.Image,
    elements: Sequence[Element],
    *,
    offset: tuple[int, int] = (0, 0),
) -> Image.Image:
    """Return a copy of `image` with red boxes and index tags drawn per `marks_layout`."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    font = _load_font()
    for index, (tl, tt, tr, tb), (left, top, right, bottom) in marks_layout(
        elements, out.size, offset=offset, measure=lambda text: _tag_size(font, text),
    ):
        draw.rectangle([left, top, right, bottom], outline=_BOX_COLOR, width=_BOX_WIDTH)
        if tl != left:  # tag outside the box: leader line to the nearest box corner
            draw.line([(tr if tl < left else tl, tt + (tb - tt) // 2), (left if tl < left else right, top)],
                      fill=_BOX_COLOR, width=_LEADER_WIDTH)
        draw.rectangle([tl, tt, tr, tb], fill=_BOX_COLOR)
        draw.text((tl + 3, tt + 2), str(index), fill=(255, 255, 255), font=font)
    return out


def fit_width(image: Image.Image, width: int = 1280) -> Image.Image:
    """Downscale `image` to `width`, preserving aspect ratio. Never upscales."""
    if image.width <= width:
        return image
    ratio = width / image.width
    height = max(1, round(image.height * ratio))
    return image.resize((width, height), Image.LANCZOS)


def to_png_bytes(image: Image.Image) -> bytes:
    """Encode `image` as optimized PNG bytes."""
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def crop_element(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    pad: int = 4,
) -> Image.Image:
    """Crop `image` to `bbox` expanded by `pad` px, clamped to image bounds."""
    left, top, right, bottom = bbox
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(image.width, right + pad)
    bottom = min(image.height, bottom + pad)
    if right <= left:
        right = left + 1
    if bottom <= top:
        bottom = top + 1
    return image.crop((left, top, right, bottom))
