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
    """Inject a fake `fitz` (pymupdf) module for scanned-vs-digital detection
    and chunk-splitting tests.

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
            self.inserted_ranges = []  # records (from_page, to_page) insert_pdf calls
            self.saved_to = None
        def __len__(self):
            return len(self._pages)
        def __getitem__(self, idx):
            return self._pages[idx]
        def close(self):
            pass
        def insert_pdf(self, src, from_page=0, to_page=None):
            self.inserted_ranges.append((from_page, to_page))
        def save(self, path):
            self.saved_to = path
            Path(path).write_bytes(b"fake chunk pdf bytes")

    class _FakeFitz:
        @staticmethod
        def open(path=None):
            if path is None:
                return _FakeDoc([])  # new empty doc, for splitting output
            pages = [_FakePage("x" * chars_per_page) for _ in range(num_pages)]
            return _FakeDoc(pages)

    fake_module = type(sys)("fitz")
    fake_module.open = _FakeFitz.open
    monkeypatch.setitem(sys.modules, "fitz", fake_module)


from tools._pdf_convert import parse_page_spec, select_pages, _PAGE_BREAK_SENTINEL


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


def _install_fake_docling(
    monkeypatch, *, markdown="# Fake\n\nContent.", captured_calls=None, convert_error=None
):
    """Inject a fake docling module that returns predetermined markdown.

    If `captured_calls` is a list, each DocumentConverter(...) construction
    appends the `format_options` kwarg it received, so callers can assert on
    the pipeline options (e.g. do_ocr) that _convert_pdf_digital passed in.
    If `convert_error` is set, .convert() raises it instead of succeeding.
    """
    class _FakeDocument:
        def __init__(self, md):
            self._md = md
        def export_to_markdown(self, page_break_placeholder=None):
            return self._md

    class _FakeResult:
        def __init__(self, md):
            self.document = _FakeDocument(md)

    class _FakeConverter:
        def __init__(self, format_options=None):
            if captured_calls is not None:
                captured_calls.append(format_options)
        def convert(self, path):
            if convert_error is not None:
                raise convert_error
            return _FakeResult(markdown)

    class _FakeInputFormat:
        PDF = "pdf"

    class _FakePdfPipelineOptions:
        def __init__(self):
            self.do_ocr = True

    class _FakePdfFormatOption:
        def __init__(self, pipeline_options=None):
            self.pipeline_options = pipeline_options

    class _FakeAcceleratorDevice:
        CPU = "cpu"

    class _FakeAcceleratorOptions:
        def __init__(self, device=None):
            self.device = device

    fake_dc_module = type(sys)("docling.document_converter")
    fake_dc_module.DocumentConverter = _FakeConverter
    fake_dc_module.PdfFormatOption = _FakePdfFormatOption

    fake_base_models_module = type(sys)("docling.datamodel.base_models")
    fake_base_models_module.InputFormat = _FakeInputFormat

    fake_pipeline_options_module = type(sys)("docling.datamodel.pipeline_options")
    fake_pipeline_options_module.PdfPipelineOptions = _FakePdfPipelineOptions
    fake_pipeline_options_module.AcceleratorDevice = _FakeAcceleratorDevice
    fake_pipeline_options_module.AcceleratorOptions = _FakeAcceleratorOptions

    fake_datamodel_module = type(sys)("docling.datamodel")
    fake_datamodel_module.base_models = fake_base_models_module
    fake_datamodel_module.pipeline_options = fake_pipeline_options_module

    fake_docling = type(sys)("docling")
    fake_docling.document_converter = fake_dc_module
    fake_docling.datamodel = fake_datamodel_module

    monkeypatch.setitem(sys.modules, "docling", fake_docling)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_dc_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel", fake_datamodel_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", fake_base_models_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", fake_pipeline_options_module)


def _install_fake_ocrmypdf(monkeypatch, *, should_fail=False, captured_calls=None):
    """Inject a fake ocrmypdf module. Its ocr() copies the input to the output path.

    If `captured_calls` is a list, each ocr(...) call appends its kwargs, so
    callers can assert on e.g. the `jobs` value _convert_pdf_scanned passed in.
    """
    import shutil

    def _fake_ocr(input_path, output_path, **kwargs):
        if captured_calls is not None:
            captured_calls.append(kwargs)
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
        # page_count // 4 == 0, floored to the never-below-1 minimum

        assert _estimate_worker_count(page_count=3) == 1

    def test_capped_by_page_count_div_4(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 16)
        _install_fake_psutil(monkeypatch, available_bytes=100 * 1024**3)
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {})
        # 50 // 4 == 12, well under the CPU/RAM caps

        assert _estimate_worker_count(page_count=50) == 12

    def test_capped_by_available_ram(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 16)
        _install_fake_psutil(monkeypatch, available_bytes=10 * 1024**3)  # 10GB free
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {})
        # 10GB / 4.0GB per worker (default worker_ram_gb) = 2 workers

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


from tools._pdf_convert import _renumber_markers


class TestRenumberMarkers:
    def test_single_marker_offset(self):
        md = "<!-- Page 1 -->\n# Chunk content"
        result = _renumber_markers(md, start_offset=5)
        assert "<!-- Page 5 -->" in result
        assert "<!-- Page 1 -->" not in result

    def test_multiple_markers_offset(self):
        md = "<!-- Page 1 -->\nA\n<!-- Page 2 -->\nB\n<!-- Page 3 -->\nC"
        result = _renumber_markers(md, start_offset=10)
        assert "<!-- Page 10 -->" in result
        assert "<!-- Page 11 -->" in result
        assert "<!-- Page 12 -->" in result

    def test_start_offset_one_is_identity(self):
        md = "<!-- Page 1 -->\nA\n<!-- Page 2 -->\nB"
        result = _renumber_markers(md, start_offset=1)
        assert result == md

    def test_content_around_markers_preserved(self):
        md = "<!-- Page 1 -->\n# Title\n\nBody text here.\n"
        result = _renumber_markers(md, start_offset=3)
        assert "# Title" in result
        assert "Body text here." in result


from tools._pdf_convert import ChunkSpec, _split_into_chunks


class TestSplitIntoChunks:
    def test_even_split(self, tmp_path, monkeypatch):
        _install_fake_fitz(monkeypatch, num_pages=20)
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake pdf bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        chunks = _split_into_chunks(pdf, cache_dir, worker_count=4)

        assert len(chunks) == 4
        assert [c.start_offset for c in chunks] == [1, 6, 11, 16]
        assert [c.chunk_index for c in chunks] == [0, 1, 2, 3]
        for c in chunks:
            assert c.path.exists()

    def test_uneven_split_front_loads_remainder(self, tmp_path, monkeypatch):
        _install_fake_fitz(monkeypatch, num_pages=22)
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake pdf bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        chunks = _split_into_chunks(pdf, cache_dir, worker_count=4)

        # 22 pages / 4 workers = 6,6,5,5
        assert [c.start_offset for c in chunks] == [1, 7, 13, 18]

    def test_single_worker_single_chunk(self, tmp_path, monkeypatch):
        _install_fake_fitz(monkeypatch, num_pages=5)
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake pdf bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        chunks = _split_into_chunks(pdf, cache_dir, worker_count=1)

        assert len(chunks) == 1
        assert chunks[0].start_offset == 1

    def test_chunk_files_named_uniquely(self, tmp_path, monkeypatch):
        _install_fake_fitz(monkeypatch, num_pages=10)
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"fake pdf bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        chunks = _split_into_chunks(pdf, cache_dir, worker_count=3)

        paths = {c.path for c in chunks}
        assert len(paths) == 3  # all distinct
        assert all(p.parent == cache_dir for p in paths)


from tools._pdf_convert import _convert_chunk


class TestConvertChunk:
    def test_digital_chunk_renumbered(self, tmp_path, monkeypatch):
        md = "# Chunk Title\n\nBody."
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        _install_fake_docling(monkeypatch, markdown=md)
        chunk_path = tmp_path / "doc_chunk0.pdf"
        chunk_path.write_bytes(b"fake chunk bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        idx, result_md = _convert_chunk(chunk_path, False, 5, 2, cache_dir)

        assert idx == 2
        assert "<!-- Page 5 -->" in result_md
        assert "# Chunk Title" in result_md

    def test_scanned_chunk_routes_through_ocr_then_renumbered(self, tmp_path, monkeypatch):
        md = "# OCR Chunk\n\nBody."
        _install_fake_fitz(monkeypatch, chars_per_page=0)
        _install_fake_docling(monkeypatch, markdown=md)
        _install_fake_ocrmypdf(monkeypatch)
        chunk_path = tmp_path / "doc_chunk1.pdf"
        chunk_path.write_bytes(b"fake chunk bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        idx, result_md = _convert_chunk(chunk_path, True, 10, 1, cache_dir)

        assert idx == 1
        assert "<!-- Page 10 -->" in result_md
        assert "# OCR Chunk" in result_md

    def test_scanned_chunk_caps_ocrmypdf_to_one_job(self, tmp_path, monkeypatch):
        # Regression test: ocrmypdf.ocr() defaults its own internal
        # page-level parallelism to os.cpu_count() when jobs is unset. A
        # chunk worker is already one of worker_count sibling processes in
        # the outer ProcessPoolExecutor, so letting ocrmypdf spin up its own
        # CPU-count pool inside each of those oversubscribes CPU/RAM by a
        # factor of worker_count -- the same class of resource exhaustion
        # (BrokenProcessPool / OOM) fixed for docling's OCR path.
        md = "# OCR Chunk\n\nBody."
        captured_calls = []
        _install_fake_fitz(monkeypatch, chars_per_page=0)
        _install_fake_docling(monkeypatch, markdown=md)
        _install_fake_ocrmypdf(monkeypatch, captured_calls=captured_calls)
        chunk_path = tmp_path / "doc_chunk1.pdf"
        chunk_path.write_bytes(b"fake chunk bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        _convert_chunk(chunk_path, True, 10, 1, cache_dir)

        assert len(captured_calls) == 1
        assert captured_calls[0]["jobs"] == 1


from tools._pdf_convert import convert_pdf


import concurrent.futures

from tools._pdf_convert import _convert_pdf_parallel


class TestConvertPdfParallel:
    def test_merges_chunks_in_order(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools._pdf_convert.ProcessPoolExecutor",
            concurrent.futures.ThreadPoolExecutor,
        )
        _install_fake_fitz(monkeypatch, num_pages=10)
        _install_fake_docling(monkeypatch, markdown="chunk-content")
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake pdf bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        result = _convert_pdf_parallel(pdf, cache_dir, False, page_count=10, worker_count=2)

        # 2 workers over 10 pages -> chunks starting at page 1 and page 6
        assert "<!-- Page 1 -->" in result
        assert "<!-- Page 6 -->" in result
        assert result.count("chunk-content") == 2

    def test_chunk_temp_files_cleaned_up(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools._pdf_convert.ProcessPoolExecutor",
            concurrent.futures.ThreadPoolExecutor,
        )
        _install_fake_fitz(monkeypatch, num_pages=10)
        _install_fake_docling(monkeypatch, markdown="content")
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake pdf bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        _convert_pdf_parallel(pdf, cache_dir, False, page_count=10, worker_count=2)

        leftover_chunks = list(cache_dir.glob("*_chunk*.pdf"))
        assert leftover_chunks == []

    def test_worker_failure_propagates_and_cleans_up(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools._pdf_convert.ProcessPoolExecutor",
            concurrent.futures.ThreadPoolExecutor,
        )
        _install_fake_fitz(monkeypatch, num_pages=10)
        _install_fake_docling(monkeypatch, convert_error=RuntimeError("docling exploded"))

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake pdf bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with pytest.raises(RuntimeError, match="docling exploded"):
            _convert_pdf_parallel(pdf, cache_dir, False, page_count=10, worker_count=2)

        leftover_chunks = list(cache_dir.glob("*_chunk*.pdf"))
        assert leftover_chunks == []


class TestConvertPdf:
    def test_digital_pdf_returns_markdown_and_cache_path(
        self, tmp_path, monkeypatch
    ):
        md = "# Title\n\nBody."
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        _install_fake_docling(monkeypatch, markdown=md)
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        text, cache_path = convert_pdf(pdf, tmp_path)

        assert "# Title" in text
        assert cache_path.exists()
        assert cache_path.parent == tmp_path / ".dagi" / "hash_cache" / "pdf"

    def test_digital_pdf_disables_docling_ocr(self, tmp_path, monkeypatch):
        # Regression test: docling's default pipeline runs OCR (loading the
        # full RapidOCR/onnxruntime/torch stack) even for PDFs with an
        # extractable text layer. For a PDF already classified as
        # digital-native, that's wasted work -- and under the parallel
        # conversion path, concurrent OCR-stack loads across worker
        # processes have exhausted memory and crashed (WinError 1114,
        # std::bad_alloc). _convert_pdf_digital must explicitly disable it.
        md = "# Title\n\nBody."
        captured_calls = []
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        _install_fake_docling(monkeypatch, markdown=md, captured_calls=captured_calls)
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        convert_pdf(pdf, tmp_path)

        assert len(captured_calls) == 1
        format_options = captured_calls[0]
        pipeline_options = format_options["pdf"].pipeline_options
        assert pipeline_options.do_ocr is False

    def test_scanned_pdf_routes_through_ocrmypdf(
        self, tmp_path, monkeypatch
    ):
        md = "# OCR Title\n\nOCR body."
        _install_fake_fitz(monkeypatch, chars_per_page=0)
        _install_fake_docling(monkeypatch, markdown=md)
        _install_fake_ocrmypdf(monkeypatch)
        pdf = tmp_path / "scan.pdf"
        pdf.write_bytes(b"fake scanned pdf bytes")

        text, cache_path = convert_pdf(pdf, tmp_path)

        assert "# OCR Title" in text
        assert cache_path.exists()

    def test_single_process_scanned_pdf_leaves_ocrmypdf_jobs_unset(
        self, tmp_path, monkeypatch
    ):
        # Single-process path: no outer worker pool to oversubscribe, so
        # ocrmypdf should keep its own default (os.cpu_count()) parallelism
        # rather than being capped to 1 -- that cap only applies inside
        # _convert_chunk, one of several sibling processes.
        md = "# OCR Title\n\nOCR body."
        captured_calls = []
        _install_fake_fitz(monkeypatch, chars_per_page=0)
        _install_fake_docling(monkeypatch, markdown=md)
        _install_fake_ocrmypdf(monkeypatch, captured_calls=captured_calls)
        pdf = tmp_path / "scan.pdf"
        pdf.write_bytes(b"fake scanned pdf bytes")

        convert_pdf(pdf, tmp_path)

        assert len(captured_calls) == 1
        assert captured_calls[0]["jobs"] is None

    def test_cache_hit_skips_conversion(self, tmp_path, monkeypatch):
        md = "# Cached\n\nContent."
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
        md1 = "# Version 1"
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        _install_fake_docling(monkeypatch, markdown=md1)
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"version 1 content")

        text1, path1 = convert_pdf(pdf, tmp_path)

        # Change the PDF content (different hash)
        pdf.write_bytes(b"version 2 content")
        md2 = "# Version 2"
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

    def test_docling_dependency_import_failure_is_not_reported_as_missing(
        self, tmp_path, monkeypatch
    ):
        """docling itself present, but a submodule import fails (e.g. a native
        extension DLL load error from onnxruntime) -- this must NOT be reported
        as "docling is not installed", since pip installing it again won't help.
        """
        _install_fake_fitz(monkeypatch, chars_per_page=500)
        # A real module, present in sys.modules, but missing the names
        # _convert_pdf_digital expects -- `from ... import X` then raises a
        # plain ImportError (not ModuleNotFoundError), same as a broken
        # transitive dependency (e.g. onnxruntime's DLL load failing).
        broken_dc_module = type(sys)("docling.document_converter")
        fake_docling = type(sys)("docling")
        fake_docling.document_converter = broken_dc_module
        monkeypatch.setitem(sys.modules, "docling", fake_docling)
        monkeypatch.setitem(sys.modules, "docling.document_converter", broken_dc_module)
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"fake pdf bytes")

        with pytest.raises(RuntimeError, match="dependency failed to import") as exc_info:
            convert_pdf(pdf, tmp_path)
        assert "docling is not installed" not in str(exc_info.value)

    def test_scanned_pdf_without_ocrmypdf_warns_and_tries_docling(
        self, tmp_path, monkeypatch
    ):
        md = "# Degraded"
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
        md = "# Clean"
        _install_fake_fitz(monkeypatch, chars_per_page=0)
        _install_fake_docling(monkeypatch, markdown=md)
        _install_fake_ocrmypdf(monkeypatch)
        pdf = tmp_path / "scan.pdf"
        pdf.write_bytes(b"fake scanned pdf bytes")

        convert_pdf(pdf, tmp_path)

        cache_dir = tmp_path / ".dagi" / "hash_cache" / "pdf"
        ocr_files = list(cache_dir.glob("*_ocr.pdf"))
        assert ocr_files == []

    def test_large_pdf_uses_parallel_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools._pdf_convert.ProcessPoolExecutor",
            concurrent.futures.ThreadPoolExecutor,
        )
        monkeypatch.setattr("os.cpu_count", lambda: 4)
        _install_fake_psutil(monkeypatch, available_bytes=100 * 1024**3)
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {})
        _install_fake_fitz(monkeypatch, chars_per_page=500, num_pages=20)
        _install_fake_docling(monkeypatch, markdown="content")
        pdf = tmp_path / "big.pdf"
        pdf.write_bytes(b"fake big pdf bytes")

        text, cache_path_result = convert_pdf(pdf, tmp_path)

        assert "<!-- Page 1 -->" in text
        assert "<!-- Page 6 -->" in text  # 20 pages / 4 workers -> chunk 2 starts at page 6
        assert cache_path_result.exists()

    def test_small_pdf_stays_single_process(self, tmp_path, monkeypatch):
        # PDF_PARALLEL_MIN_PAGES is 8 -- a 3-page doc must never touch the pool
        def _fail_if_called(*args, **kwargs):
            raise AssertionError("ProcessPoolExecutor should not be constructed for small PDFs")

        monkeypatch.setattr("tools._pdf_convert.ProcessPoolExecutor", _fail_if_called)
        _install_fake_fitz(monkeypatch, chars_per_page=500, num_pages=3)
        _install_fake_docling(monkeypatch, markdown="small doc content")
        pdf = tmp_path / "small.pdf"
        pdf.write_bytes(b"fake small pdf bytes")

        text, _ = convert_pdf(pdf, tmp_path)

        assert "small doc content" in text


class TestReadToolPdf:
    # Raw docling output as it would come back from export_to_markdown(): pages
    # separated by the sentinel _convert_pdf_digital splits on, with no page
    # markers of its own -- those are added by _convert_pdf_digital itself.
    SAMPLE_PDF_MD = _PAGE_BREAK_SENTINEL.join([
        "# Title\n\nIntro paragraph.\n",
        "## Chapter 1\n\nBody text.\n",
        "## Chapter 2\n\nMore text.\n",
    ])

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
