import sys
from pathlib import Path

import pytest

from tools.read import ReadTool


def _numbered(lines, start=1):
    return "\n".join(f"{i:6d}\t{line}" for i, line in enumerate(lines, start))


def _install_fake_markitdown(monkeypatch, *, text=None, error=None):
    """Inject a fake `markitdown` module into sys.modules so tests don't need
    the real (optional) dependency installed."""

    class _FakeResult:
        def __init__(self, text_content):
            self.text_content = text_content

    class _FakeMarkItDown:
        def convert(self, path):
            if error is not None:
                raise error
            return _FakeResult(text)

    fake_module = type(sys)("markitdown")
    fake_module.MarkItDown = _FakeMarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake_module)


def _make_tool(tmp_path):
    return ReadTool(cwd=tmp_path, allowed_roots=[tmp_path])


class TestDocumentFormatConversion:
    def test_docx_file_returns_line_numbered_markdown(self, tmp_path, monkeypatch):
        _install_fake_markitdown(monkeypatch, text="# Heading\n\nSome paragraph text.")
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake docx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="doc.docx")

        assert result == _numbered(["# Heading", "", "Some paragraph text."])

    def test_xlsx_file_returns_line_numbered_markdown(self, tmp_path, monkeypatch):
        _install_fake_markitdown(monkeypatch, text="| A | B |\n| --- | --- |\n| 1 | 2 |")
        f = tmp_path / "sheet.xlsx"
        f.write_bytes(b"fake xlsx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="sheet.xlsx")

        assert result == _numbered(["| A | B |", "| --- | --- |", "| 1 | 2 |"])

    def test_pptx_file_returns_line_numbered_markdown(self, tmp_path, monkeypatch):
        _install_fake_markitdown(monkeypatch, text="## Slide 1\n\nBullet point")
        f = tmp_path / "deck.pptx"
        f.write_bytes(b"fake pptx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="deck.pptx")

        assert result == _numbered(["## Slide 1", "", "Bullet point"])

    def test_offset_and_limit_window_the_converted_output(self, tmp_path, monkeypatch):
        text = "\n".join(f"line{i}" for i in range(1, 11))  # line1..line10
        _install_fake_markitdown(monkeypatch, text=text)
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake docx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="doc.docx", offset=3, limit=2)

        assert result == _numbered(["line3", "line4"], start=3)

    def test_missing_markitdown_dependency_returns_friendly_error(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "markitdown", None)  # forces ImportError
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake docx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="doc.docx")

        assert result.startswith("Error: Could not convert 'doc.docx':")
        assert "markitdown" in result.lower()

    def test_conversion_exception_returns_friendly_error_not_traceback(self, tmp_path, monkeypatch):
        _install_fake_markitdown(monkeypatch, error=ValueError("corrupt zip"))
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake docx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="doc.docx")

        assert result == "Error: Could not convert 'doc.docx': corrupt zip"

    def test_text_files_are_unaffected_by_the_new_branch(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello\nworld", encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt")

        assert result == _numbered(["hello", "world"])
