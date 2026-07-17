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


def _install_fake_fitz(monkeypatch, *, chars_per_page=500, num_pages=3):
    """Inject a fake `fitz` (pymupdf) module for scanned-vs-digital detection tests.

    `chars_per_page` controls how much text each fake page reports —
    set to 0 to simulate a scanned (image-only) PDF.
    """
    class _FakePage:
        def __init__(self, text):
            self._text = text
        def get_text(self):
            return self._text

    class _FakeDoc:
        def __init__(self, pages):
            self._pages = pages
        def __len__(self):
            return len(self._pages)
        def __getitem__(self, idx):
            return self._pages[idx]
        def close(self):
            pass

    class _FakeFitz:
        @staticmethod
        def open(path):
            pages = [_FakePage("x" * chars_per_page) for _ in range(num_pages)]
            return _FakeDoc(pages)

    fake_module = type(sys)("fitz")
    fake_module.open = _FakeFitz.open
    monkeypatch.setitem(sys.modules, "fitz", fake_module)


from tools._pdf_convert import parse_page_spec, select_pages


class TestParsePageSpec:
    def test_single_page(self):
        assert parse_page_spec("3") == {3}

    def test_page_range(self):
        assert parse_page_spec("2-5") == {2, 3, 4, 5}

    def test_comma_separated(self):
        assert parse_page_spec("1,3,7") == {1, 3, 7}

    def test_mixed_ranges_and_singles(self):
        assert parse_page_spec("1-3,5,8-10") == {1, 2, 3, 5, 8, 9, 10}

    def test_whitespace_is_stripped(self):
        assert parse_page_spec(" 1 - 3 , 5 ") == {1, 2, 3, 5}

    def test_invalid_spec_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid page spec"):
            parse_page_spec("abc")


class TestSelectPages:
    SAMPLE_MD = (
        "<!-- Page 1 -->\n# Title\n\nIntro.\n"
        "<!-- Page 2 -->\n## Chapter 1\n\nBody.\n"
        "<!-- Page 3 -->\n## Chapter 2\n\nMore body.\n"
    )

    def test_select_single_page(self):
        result = select_pages(self.SAMPLE_MD, "2")
        assert "## Chapter 1" in result
        assert "# Title" not in result
        assert "## Chapter 2" not in result

    def test_select_page_range(self):
        result = select_pages(self.SAMPLE_MD, "1-2")
        assert "# Title" in result
        assert "## Chapter 1" in result
        assert "## Chapter 2" not in result

    def test_select_comma_separated(self):
        result = select_pages(self.SAMPLE_MD, "1,3")
        assert "# Title" in result
        assert "## Chapter 2" in result
        assert "## Chapter 1" not in result


from tools._pdf_convert import is_scanned_pdf


class TestIsScannedPdf:
    def test_digital_native_pdf_detected(self, tmp_path, monkeypatch):
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        pdf = tmp_path / "digital.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        assert is_scanned_pdf(pdf) is False

    def test_scanned_pdf_detected(self, tmp_path, monkeypatch):
        _install_fake_fitz(monkeypatch, chars_per_page=0)
        pdf = tmp_path / "scanned.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        assert is_scanned_pdf(pdf) is True

    def test_borderline_text_under_threshold_is_scanned(self, tmp_path, monkeypatch):
        _install_fake_fitz(monkeypatch, chars_per_page=10, num_pages=3)
        pdf = tmp_path / "borderline.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        assert is_scanned_pdf(pdf) is True  # 30 chars < 50 threshold

    def test_pymupdf_missing_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "fitz", None)
        pdf = tmp_path / "unknown.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        assert is_scanned_pdf(pdf) is False
