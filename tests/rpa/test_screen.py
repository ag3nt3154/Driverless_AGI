"""Tests for rpa/screen.py — screen capture and the set-of-marks overlay."""
from __future__ import annotations

import os

import pytest
from PIL import Image

from rpa.model import Element
from rpa.screen import crop_element, fit_width, mark, marks_layout, to_png_bytes


def _el(index, bbox, interactive=True, role="Button", name="x"):
    return Element(
        index=index,
        role=role,
        name=name,
        automation_id=None,
        bbox=bbox,
        value=None,
        secure=False,
        interactive=interactive,
        path=(),
    )


def _inside(outer, inner):
    ol, ot, or_, ob = outer
    il, it, ir, ib = inner
    return ol <= il and ot <= it and ir <= or_ and ib <= ob


def _overlap(a, b):
    al, at, ar, ab = a
    bl, bt, br, bb = b
    return al < br and ar > bl and at < bb and ab > bt


def test_tag_lies_inside_box_for_normal_size_box():
    el = _el(1, (10, 10, 110, 50))  # 100x40, plenty of room for a tag
    layout = marks_layout([el], image_size=(200, 200))
    assert len(layout) == 1
    index, tag_rect, box_rect = layout[0]
    assert index == 1
    assert box_rect == (10, 10, 110, 50)
    assert _inside(box_rect, tag_rect)


def test_small_box_gets_tag_to_the_left_not_overlapping():
    el = _el(2, (100, 100, 108, 108))  # 8x8, too small for any tag
    layout = marks_layout([el], image_size=(200, 200))
    index, tag_rect, box_rect = layout[0]
    assert tag_rect[2] <= box_rect[0]  # tag's right edge at/left of box's left edge
    assert tag_rect[1] == box_rect[1]  # vertically aligned with box top
    assert not _overlap(tag_rect, box_rect)


def test_non_interactive_element_gets_no_tag():
    el = _el(3, (10, 10, 110, 50), interactive=False)
    layout = marks_layout([el], image_size=(200, 200))
    assert layout == []


def test_zero_area_element_gets_no_tag():
    el = _el(4, (10, 10, 10, 50))  # zero width
    layout = marks_layout([el], image_size=(200, 200))
    assert layout == []

    el2 = _el(5, (10, 10, 50, 10))  # zero height
    layout2 = marks_layout([el2], image_size=(200, 200))
    assert layout2 == []


def test_mark_draws_only_interactive_nonzero_elements():
    img = Image.new("RGB", (300, 300), "white")
    elements = [
        _el(1, (10, 10, 110, 50)),
        _el(2, (0, 0, 0, 0), interactive=True),  # zero area, skipped
        _el(3, (20, 20, 80, 60), interactive=False),  # container, skipped
    ]
    out = mark(img, elements)
    assert out is not img  # returns a copy
    assert out.size == img.size
    # original untouched
    assert img.getpixel((0, 0)) == (255, 255, 255)


def test_mark_offset_shifts_boxes():
    img = Image.new("RGB", (300, 300), "white")
    el = _el(1, (110, 110, 210, 150))
    out_no_offset = mark(img, [el])
    out_offset = mark(img, [el], offset=(100, 100))
    # With offset, the box is drawn near (10,10) instead of (110,110);
    # pixel at (10, 10) should now show a red boxline where it didn't before.
    red_present_offset = any(
        out_offset.getpixel((x, 10)) == (255, 0, 0) for x in range(10, 20)
    )
    assert red_present_offset


def test_fit_width_never_upscales_and_keeps_aspect():
    img = Image.new("RGB", (640, 480), "white")
    out = fit_width(img, width=1280)
    assert out.size == (640, 480)  # unchanged, no upscaling

    img2 = Image.new("RGB", (2560, 1440), "white")
    out2 = fit_width(img2, width=1280)
    assert out2.width == 1280
    assert out2.height == round(1440 * (1280 / 2560))


def test_crop_element_clamps_at_image_edges():
    img = Image.new("RGB", (100, 100), "white")
    out = crop_element(img, (-10, -10, 5, 5), pad=4)
    assert out.size[0] <= 100
    assert out.size[1] <= 100

    out2 = crop_element(img, (90, 90, 150, 150), pad=4)
    assert out2.size[0] <= 100
    assert out2.size[1] <= 100


def test_to_png_bytes_round_trips():
    img = Image.new("RGB", (50, 50), (1, 2, 3))
    data = to_png_bytes(img)
    assert isinstance(data, bytes)
    import io

    round_tripped = Image.open(io.BytesIO(data))
    assert round_tripped.size == (50, 50)
    assert round_tripped.convert("RGB").getpixel((0, 0)) == (1, 2, 3)


@pytest.mark.desktop
def test_capture_window_smoke():
    from rpa.screen import capture_window

    img = capture_window((0, 0, 50, 50))
    assert img.size == (50, 50)


def test_small_box_at_the_left_edge_puts_its_tag_on_the_right_inside_the_image():
    el = _el(3, (0, 10, 6, 16))
    [(_, tag, box)] = marks_layout([el], image_size=(200, 200))
    assert tag[0] >= 0 and tag[0] == box[2]


def test_mark_draws_where_marks_layout_says():
    img = Image.new("RGB", (120, 60), "white")
    el = _el(7, (10, 10, 100, 50))
    out = mark(img, [el])
    assert out.getpixel((12, 12)) == (255, 0, 0)  # tag fill inside the top-left corner
    assert out.getpixel((60, 40)) == (255, 255, 255)  # box interior untouched
