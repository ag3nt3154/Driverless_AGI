from __future__ import annotations

from pyside_gui.markdown_renderer import render_markdown


def test_plain_text():
    result = render_markdown("Hello world")
    assert "<p>Hello world</p>" in result


def test_code_block_has_highlight_class():
    md = "```python\nprint('hi')\n```"
    result = render_markdown(md)
    assert "highlight" in result or "codehilite" in result


def test_inline_code():
    result = render_markdown("Use `foo()` here")
    assert "<code>" in result
    assert "foo()" in result


def test_heading():
    result = render_markdown("## Section Title")
    assert "<h2>" in result


def test_table():
    md = "| A | B |\n|---|---|\n| 1 | 2 |"
    result = render_markdown(md)
    assert "<table>" in result
