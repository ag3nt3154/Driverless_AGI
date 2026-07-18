import sys
from pathlib import Path
from unittest.mock import patch

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


def _install_fake_docling(monkeypatch, *, markdown="# Fake\n\nContent."):
    """Inject a fake docling module that returns predetermined markdown."""
    class _FakeDocument:
        def __init__(self, md):
            self._md = md
        def export_to_markdown(self):
            return self._md

    class _FakeResult:
        def __init__(self, md):
            self.document = _FakeDocument(md)

    class _FakeConverter:
        def convert(self, path):
            return _FakeResult(markdown)

    fake_dc_module = type(sys)("docling.document_converter")
    fake_dc_module.DocumentConverter = _FakeConverter

    fake_docling = type(sys)("docling")
    fake_docling.document_converter = fake_dc_module

    monkeypatch.setitem(sys.modules, "docling", fake_docling)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_dc_module)


def _install_fake_ocrmypdf(monkeypatch, *, should_fail=False):
    """Inject a fake ocrmypdf module. Its ocr() copies the input to the output path."""
    import shutil

    def _fake_ocr(input_path, output_path, **kwargs):
        if should_fail:
            raise RuntimeError("tesseract not found")
        shutil.copy2(input_path, output_path)

    fake_module = type(sys)("ocrmypdf")
    fake_module.ocr = _fake_ocr
    monkeypatch.setitem(sys.modules, "ocrmypdf", fake_module)


def _install_all_pdf_fakes(monkeypatch, *, markdown, chars_per_page=500):
    """Install all three fakes (fitz, docling, ocrmypdf) for full-pipeline tests."""
    _install_fake_fitz(monkeypatch, chars_per_page=chars_per_page)
    _install_fake_docling(monkeypatch, markdown=markdown)
    _install_fake_ocrmypdf(monkeypatch)


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


from tools._pdf_convert import _get_page_count


class TestGetPageCount:
    def test_counts_pages_via_fitz(self, tmp_path, monkeypatch):
        _install_fake_fitz(monkeypatch, num_pages=7)
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        assert _get_page_count(pdf) == 7

    def test_returns_zero_when_fitz_missing(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "fitz", None)
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        assert _get_page_count(pdf) == 0


def _install_fake_psutil(monkeypatch, *, available_bytes):
    """Inject a fake psutil module reporting a fixed amount of available RAM."""
    class _FakeVirtualMemory:
        def __init__(self, available):
            self.available = available

    fake_module = type(sys)("psutil")
    fake_module.virtual_memory = lambda: _FakeVirtualMemory(available_bytes)
    monkeypatch.setitem(sys.modules, "psutil", fake_module)


from tools._pdf_convert import _estimate_worker_count


class TestEstimateWorkerCount:
    def test_capped_by_cpu_count(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 2)
        _install_fake_psutil(monkeypatch, available_bytes=100 * 1024**3)  # 100GB free
        monkeypatch.setattr(
            "agent.config_loader.load_raw_config", lambda: {}
        )

        assert _estimate_worker_count(page_count=50) == 2

    def test_capped_by_page_count(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 16)
        _install_fake_psutil(monkeypatch, available_bytes=100 * 1024**3)
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {})

        assert _estimate_worker_count(page_count=3) == 3

    def test_capped_by_available_ram(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 16)
        _install_fake_psutil(monkeypatch, available_bytes=5 * 1024**3)  # 5GB free
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {})
        # 5GB / 2.0GB per worker (default worker_ram_gb) = 2 workers

        assert _estimate_worker_count(page_count=50) == 2

    def test_custom_worker_ram_gb_from_config(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 16)
        _install_fake_psutil(monkeypatch, available_bytes=10 * 1024**3)  # 10GB free
        monkeypatch.setattr(
            "agent.config_loader.load_raw_config",
            lambda: {"pdf": {"worker_ram_gb": 5.0}},
        )
        # 10GB / 5.0GB per worker = 2 workers

        assert _estimate_worker_count(page_count=50) == 2

    def test_capped_by_max_workers(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 16)
        _install_fake_psutil(monkeypatch, available_bytes=100 * 1024**3)
        monkeypatch.setattr(
            "agent.config_loader.load_raw_config",
            lambda: {"pdf": {"max_workers": 3}},
        )

        assert _estimate_worker_count(page_count=50) == 3

    def test_never_returns_less_than_one(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 16)
        _install_fake_psutil(monkeypatch, available_bytes=0)
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {})

        assert _estimate_worker_count(page_count=50) == 1


from tools._pdf_convert import convert_pdf


class TestConvertPdf:
    def test_digital_pdf_returns_markdown_and_cache_path(
        self, tmp_path, monkeypatch
    ):
        md = "<!-- Page 1 -->\n# Title\n\nBody."
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        _install_fake_docling(monkeypatch, markdown=md)
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        text, cache_path = convert_pdf(pdf, tmp_path)

        assert "# Title" in text
        assert cache_path.exists()
        assert cache_path.parent == tmp_path / ".dagi" / "hash_cache" / "pdf"

    def test_scanned_pdf_routes_through_ocrmypdf(
        self, tmp_path, monkeypatch
    ):
        md = "<!-- Page 1 -->\n# OCR Title\n\nOCR body."
        _install_fake_fitz(monkeypatch, chars_per_page=0)
        _install_fake_docling(monkeypatch, markdown=md)
        _install_fake_ocrmypdf(monkeypatch)
        pdf = tmp_path / "scan.pdf"
        pdf.write_bytes(b"fake scanned pdf bytes")

        text, cache_path = convert_pdf(pdf, tmp_path)

        assert "# OCR Title" in text
        assert cache_path.exists()

    def test_cache_hit_skips_conversion(self, tmp_path, monkeypatch):
        md = "<!-- Page 1 -->\n# Cached\n\nContent."
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        _install_fake_docling(monkeypatch, markdown=md)
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        text1, path1 = convert_pdf(pdf, tmp_path)
        # Nuke the fake docling — if cache works, second call won't need it
        monkeypatch.setitem(sys.modules, "docling", None)
        monkeypatch.setitem(sys.modules, "docling.document_converter", None)
        text2, path2 = convert_pdf(pdf, tmp_path)

        assert text1 == text2
        assert path1 == path2

    def test_cache_invalidated_when_pdf_changes(self, tmp_path, monkeypatch):
        md1 = "<!-- Page 1 -->\n# Version 1"
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        _install_fake_docling(monkeypatch, markdown=md1)
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"version 1 content")

        text1, path1 = convert_pdf(pdf, tmp_path)

        # Change the PDF content (different hash)
        pdf.write_bytes(b"version 2 content")
        md2 = "<!-- Page 1 -->\n# Version 2"
        _install_fake_docling(monkeypatch, markdown=md2)

        text2, path2 = convert_pdf(pdf, tmp_path)

        assert "Version 1" in text1
        assert "Version 2" in text2
        assert path1 != path2  # different hash → different cache file

    def test_missing_docling_raises_runtime_error(self, tmp_path, monkeypatch):
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        monkeypatch.setitem(sys.modules, "docling", None)
        monkeypatch.setitem(sys.modules, "docling.document_converter", None)
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        with pytest.raises(RuntimeError, match="docling is not installed"):
            convert_pdf(pdf, tmp_path)

    def test_scanned_pdf_without_ocrmypdf_warns_and_tries_docling(
        self, tmp_path, monkeypatch
    ):
        md = "<!-- Page 1 -->\n# Degraded"
        _install_fake_fitz(monkeypatch, chars_per_page=0)
        _install_fake_docling(monkeypatch, markdown=md)
        monkeypatch.setitem(sys.modules, "ocrmypdf", None)
        pdf = tmp_path / "scan.pdf"
        pdf.write_bytes(b"fake scanned pdf bytes")

        text, cache_path = convert_pdf(pdf, tmp_path)

        assert "# Degraded" in text
        assert cache_path.exists()

    def test_intermediate_ocr_pdf_is_cleaned_up(
        self, tmp_path, monkeypatch
    ):
        md = "<!-- Page 1 -->\n# Clean"
        _install_fake_fitz(monkeypatch, chars_per_page=0)
        _install_fake_docling(monkeypatch, markdown=md)
        _install_fake_ocrmypdf(monkeypatch)
        pdf = tmp_path / "scan.pdf"
        pdf.write_bytes(b"fake scanned pdf bytes")

        convert_pdf(pdf, tmp_path)

        cache_dir = tmp_path / ".dagi" / "hash_cache" / "pdf"
        ocr_files = list(cache_dir.glob("*_ocr.pdf"))
        assert ocr_files == []


class TestReadToolPdf:
    SAMPLE_PDF_MD = (
        "<!-- Page 1 -->\n# Title\n\nIntro paragraph.\n"
        "<!-- Page 2 -->\n## Chapter 1\n\nBody text.\n"
        "<!-- Page 3 -->\n## Chapter 2\n\nMore text.\n"
    )

    def test_pdf_returns_metadata_header_and_numbered_lines(
        self, tmp_path, monkeypatch
    ):
        _install_all_pdf_fakes(monkeypatch, markdown=self.SAMPLE_PDF_MD)
        (tmp_path / "report.pdf").write_bytes(b"fake pdf")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf")

        assert result.startswith("[PDF: report.pdf |")
        assert "cached:" in result
        assert "# Title" in result

    def test_pdf_pages_parameter_filters_output(
        self, tmp_path, monkeypatch
    ):
        _install_all_pdf_fakes(monkeypatch, markdown=self.SAMPLE_PDF_MD)
        (tmp_path / "report.pdf").write_bytes(b"fake pdf")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf", pages="2")

        assert "## Chapter 1" in result
        assert "# Title" not in result
        assert "## Chapter 2" not in result
        assert "showing pages 2" in result

    def test_pdf_offset_limit_applied_after_pages(
        self, tmp_path, monkeypatch
    ):
        _install_all_pdf_fakes(monkeypatch, markdown=self.SAMPLE_PDF_MD)
        (tmp_path / "report.pdf").write_bytes(b"fake pdf")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf", pages="1", offset=2, limit=1)

        lines = result.split("\n")
        # First line is the metadata header
        content_lines = [l for l in lines if not l.startswith("[PDF:")]
        assert len(content_lines) == 1

    def test_pages_parameter_on_non_pdf_returns_error(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt", pages="1-3")

        assert result == "Error: 'pages' parameter is only supported for PDF files."

    def test_missing_docling_returns_friendly_error(
        self, tmp_path, monkeypatch
    ):
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        monkeypatch.setitem(sys.modules, "docling", None)
        monkeypatch.setitem(sys.modules, "docling.document_converter", None)
        (tmp_path / "report.pdf").write_bytes(b"fake pdf")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf")

        assert result.startswith("Error: Could not convert 'report.pdf':")
        assert "docling" in result.lower()

    def test_text_files_unaffected_by_pdf_branch(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hello\nworld", encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt")

        assert result == _numbered(["hello", "world"])


class TestAutoSummarization:
    def test_large_file_triggers_summarization(self, tmp_path):
        content = "line\n" * 100_000  # ~500k chars → ~125k tokens
        f = tmp_path / "huge.txt"
        f.write_text(content, encoding="utf-8")
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=16_384,
            project_path=tmp_path,
        )

        fake_summary = "## Section 1 (lines 1-2000, ~2500 tokens)\n**Summary:** lots of lines"

        with patch(
            "tools.read.summarize_document", return_value=fake_summary
        ) as mock_summarize:
            result = tool.run(path="huge.txt")

        assert result == fake_summary
        mock_summarize.assert_called_once()

    def test_small_file_does_not_trigger_summarization(self, tmp_path):
        content = "short file\nonly two lines\n"
        f = tmp_path / "small.txt"
        f.write_text(content, encoding="utf-8")
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=16_384,
            project_path=tmp_path,
        )

        with patch(
            "tools.read.summarize_document"
        ) as mock_summarize:
            result = tool.run(path="small.txt")

        mock_summarize.assert_not_called()
        assert "short file" in result

    def test_summarization_failure_falls_back_to_raw_text(self, tmp_path):
        content = "line\n" * 100_000
        f = tmp_path / "huge.txt"
        f.write_text(content, encoding="utf-8")
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=16_384,
            project_path=tmp_path,
        )

        with patch(
            "tools.read.summarize_document", return_value=None
        ):
            result = tool.run(path="huge.txt")

        # Falls back to raw text (which output_filter will later truncate)
        assert "line" in result
