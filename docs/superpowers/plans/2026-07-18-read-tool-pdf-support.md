# ReadTool PDF Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ReadTool` (`tools/read.py`) transparently converts `.pdf` files to line-numbered markdown via a dual pipeline — `docling` for digital-native PDFs, `ocrmypdf` + `docling` for scanned PDFs — with a SHA-256 file-content cache in `.dagi/pdf_cache/` so repeat reads are instant. A new `pages` parameter lets the LLM request specific page ranges. All four dependencies (`docling`, `pymupdf`, `ocrmypdf`, `tesseract`) are optional; the tool degrades gracefully.

**Architecture:** PDF conversion lives in a new `tools/_pdf_convert.py` module (keeps `read.py` lean — it's already 100 lines after the DOCX/XLSX/PPTX work). `_pdf_convert.py` exports one public function `convert_pdf(pdf_path, project_root) -> (markdown, cache_path)` plus two helpers `parse_page_spec(spec) -> set[int]` and `select_pages(markdown, spec) -> str`. `ReadTool.run()` gains a `pages` parameter and a new `ext == ".pdf"` branch that calls into `_pdf_convert`, applies page filtering, then falls through to the existing offset/limit + line-numbering logic. The output includes a metadata header with the cache path.

**Tech Stack:** Python 3.14, `docling` (PDF → markdown with TableFormer), `pymupdf` (scanned-vs-digital detection), `ocrmypdf` (tesseract-based OCR overlay), pytest with `monkeypatch`/`sys.modules` mocking (no real binary fixtures).

Spec: `docs/superpowers/specs/2026-07-18-read-tool-pdf-support-design.md`

---

### Task 1: Declare the optional PDF dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the optional dependency section**

In `requirements.txt`, after the existing `# ── Optional: document reading (DOCX/XLSX/PPTX) ──` section at the end of the file, add:

```
# ── Optional: PDF reading ────────────────────────────────────────────────────
# Install to enable PDF reading in the `read` tool.
# dagi starts and runs without these; PDF files return a friendly error message.
# docling>=2.0             # IBM deep-learning document converter (TableFormer for tables)
# pymupdf>=1.24            # Scanned-vs-digital PDF detection (text extraction probe)
# ocrmypdf>=16.0           # Tesseract-based OCR overlay for scanned PDFs
# NOTE: ocrmypdf requires the `tesseract` system binary — install via your OS package manager.
```

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "docs: declare docling/pymupdf/ocrmypdf as optional PDF dependencies"
```

---

### Task 2: Write failing tests for page-spec parsing and page selection

**Files:**
- Modify: `tests/test_read_tool.py`

These two helpers are pure functions with no dependency on docling/pymupdf/ocrmypdf, so they can be tested without any mocking.

- [ ] **Step 1: Write the failing tests**

Add the following at the end of `tests/test_read_tool.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py::TestParsePageSpec tests/test_read_tool.py::TestSelectPages -v`

Expected: All tests FAIL with `ModuleNotFoundError: No module named 'tools._pdf_convert'` — the module doesn't exist yet.

- [ ] **Step 3: Commit**

```bash
git add tests/test_read_tool.py
git commit -m "test: add failing tests for parse_page_spec and select_pages"
```

---

### Task 3: Implement `parse_page_spec` and `select_pages` in `_pdf_convert.py`

**Files:**
- Create: `tools/_pdf_convert.py`

- [ ] **Step 1: Create the module with the two pure helpers**

Create `tools/_pdf_convert.py`:

```python
"""tools/_pdf_convert.py — PDF-to-markdown conversion with caching.

Digital-native PDFs are converted via docling (TableFormer for tables).
Scanned PDFs are first OCR'd via ocrmypdf (tesseract), then converted via docling.
All four dependencies (docling, pymupdf, ocrmypdf, tesseract) are optional;
the tool degrades gracefully with friendly error messages.
"""
from __future__ import annotations

import re
from pathlib import Path


def parse_page_spec(spec: str) -> set[int]:
    """Parse a page spec like '1-3,5,8-10' into a set of 1-indexed page numbers."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                start, end = int(bounds[0].strip()), int(bounds[1].strip())
            except ValueError:
                raise ValueError(f"Invalid page spec: '{spec}'")
            pages.update(range(start, end + 1))
        else:
            try:
                pages.add(int(part))
            except ValueError:
                raise ValueError(f"Invalid page spec: '{spec}'")
    return pages


def select_pages(markdown: str, pages_spec: str) -> str:
    """Filter cached markdown by page markers (<!-- Page N -->)."""
    requested = parse_page_spec(pages_spec)
    sections = re.split(r"(<!-- Page \d+ -->)", markdown)

    result_parts: list[str] = []
    current_page = 0
    for section in sections:
        page_match = re.match(r"<!-- Page (\d+) -->", section)
        if page_match:
            current_page = int(page_match.group(1))
            if current_page in requested:
                result_parts.append(section)
        elif current_page in requested:
            result_parts.append(section)

    return "".join(result_parts)
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py::TestParsePageSpec tests/test_read_tool.py::TestSelectPages -v`

Expected: All 9 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tools/_pdf_convert.py
git commit -m "feat: add parse_page_spec and select_pages helpers for PDF page filtering"
```

---

### Task 4: Write failing tests for the scanned-vs-digital detection

**Files:**
- Modify: `tests/test_read_tool.py`

- [ ] **Step 1: Write a helper to install a fake `fitz` module**

Add this helper function below the existing `_install_fake_markitdown` function in `tests/test_read_tool.py`:

```python
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
```

- [ ] **Step 2: Write the failing detection tests**

Add this test class at the end of `tests/test_read_tool.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py::TestIsScannedPdf -v`

Expected: All 4 tests FAIL with `ImportError: cannot import name 'is_scanned_pdf' from 'tools._pdf_convert'` — the function doesn't exist yet.

- [ ] **Step 4: Commit**

```bash
git add tests/test_read_tool.py
git commit -m "test: add failing tests for scanned-vs-digital PDF detection"
```

---

### Task 5: Implement `is_scanned_pdf` in `_pdf_convert.py`

**Files:**
- Modify: `tools/_pdf_convert.py`

- [ ] **Step 1: Add the detection function**

In `tools/_pdf_convert.py`, add this function after the `select_pages` function:

```python
_SCANNED_CHAR_THRESHOLD = 50


def is_scanned_pdf(pdf_path: Path, sample_pages: int = 3) -> bool:
    """Probe first N pages for extractable text. Returns True if scanned."""
    try:
        import fitz
    except ImportError:
        return False
    doc = fitz.open(str(pdf_path))
    pages_to_check = min(sample_pages, len(doc))
    total_chars = sum(len(doc[i].get_text()) for i in range(pages_to_check))
    doc.close()
    return total_chars < _SCANNED_CHAR_THRESHOLD
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py::TestIsScannedPdf -v`

Expected: All 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tools/_pdf_convert.py
git commit -m "feat: add is_scanned_pdf detection via pymupdf text probe"
```

---

### Task 6: Write failing tests for the conversion + cache pipeline

**Files:**
- Modify: `tests/test_read_tool.py`

This is the core pipeline test suite. It mocks all three external dependencies (`docling`, `fitz`, `ocrmypdf`) and tests the `convert_pdf` orchestrator function, including cache behaviour.

- [ ] **Step 1: Write helpers to install fake `docling` and `ocrmypdf` modules**

Add these helpers below the existing `_install_fake_fitz` function in `tests/test_read_tool.py`:

```python
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
```

- [ ] **Step 2: Write the failing pipeline tests**

Add this test class at the end of `tests/test_read_tool.py`:

```python
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
        assert cache_path.parent.name == "pdf_cache"

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

        cache_dir = tmp_path / ".dagi" / "pdf_cache"
        ocr_files = list(cache_dir.glob("*_ocr.pdf"))
        assert ocr_files == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py::TestConvertPdf -v`

Expected: All 7 tests FAIL with `ImportError: cannot import name 'convert_pdf' from 'tools._pdf_convert'` — the function doesn't exist yet.

- [ ] **Step 4: Commit**

```bash
git add tests/test_read_tool.py
git commit -m "test: add failing tests for convert_pdf pipeline and cache"
```

---

### Task 7: Implement `convert_pdf` pipeline in `_pdf_convert.py`

**Files:**
- Modify: `tools/_pdf_convert.py`

- [ ] **Step 1: Add the conversion functions**

In `tools/_pdf_convert.py`, add these imports at the top (after the existing `from __future__ import annotations`):

```python
import hashlib
```

Then add these functions after the `is_scanned_pdf` function:

```python
_PDF_CACHE_DIR = ".dagi/pdf_cache"


def _convert_pdf_digital(pdf_path: Path) -> str:
    """Convert a digital-native PDF to markdown via docling."""
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        raise RuntimeError(
            "docling is not installed. Install it with: pip install docling"
        )
    converter = DocumentConverter()
    result = converter.convert(str(pdf_path))
    return result.document.export_to_markdown()


def _convert_pdf_scanned(pdf_path: Path, cache_dir: Path) -> str:
    """OCR a scanned PDF via ocrmypdf, then convert via docling."""
    try:
        import ocrmypdf
    except ImportError:
        return _convert_pdf_digital(pdf_path)

    searchable_path = cache_dir / f"{pdf_path.stem}_ocr.pdf"
    try:
        ocrmypdf.ocr(
            str(pdf_path),
            str(searchable_path),
            skip_text=True,
            force_ocr=False,
        )
        return _convert_pdf_digital(searchable_path)
    finally:
        searchable_path.unlink(missing_ok=True)


def _get_pdf_cache_path(
    pdf_path: Path, project_root: Path
) -> tuple[Path, str]:
    """Return (cache_file_path, hex_hash) for a PDF."""
    content_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    cache_dir = project_root / _PDF_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{content_hash}.md", content_hash


def convert_pdf(
    pdf_path: Path, project_root: Path
) -> tuple[str, Path]:
    """Convert a PDF to markdown, using cache if available.

    Returns (markdown_text, cache_file_path).
    """
    cache_path, _ = _get_pdf_cache_path(pdf_path, project_root)

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8"), cache_path

    if is_scanned_pdf(pdf_path):
        md_text = _convert_pdf_scanned(pdf_path, cache_path.parent)
    else:
        md_text = _convert_pdf_digital(pdf_path)

    cache_path.write_text(md_text, encoding="utf-8", newline="\n")
    return md_text, cache_path
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py::TestConvertPdf -v`

Expected: All 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tools/_pdf_convert.py
git commit -m "feat: add convert_pdf pipeline with docling, ocrmypdf, and SHA-256 cache"
```

---

### Task 8: Write failing tests for ReadTool PDF integration

**Files:**
- Modify: `tests/test_read_tool.py`

These tests exercise the full path through `ReadTool.run()` — the `pages` parameter, the metadata header in the output, error messages, and confirming the `pages` parameter is rejected for non-PDF files.

- [ ] **Step 1: Write a combined setup helper**

Add this helper below the existing mock helpers in `tests/test_read_tool.py`:

```python
def _install_all_pdf_fakes(monkeypatch, *, markdown, chars_per_page=500):
    """Install all three fakes (fitz, docling, ocrmypdf) for full-pipeline tests."""
    _install_fake_fitz(monkeypatch, chars_per_page=chars_per_page)
    _install_fake_docling(monkeypatch, markdown=markdown)
    _install_fake_ocrmypdf(monkeypatch)
```

- [ ] **Step 2: Write the failing integration tests**

Add this test class at the end of `tests/test_read_tool.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py::TestReadToolPdf -v`

Expected: All 6 tests FAIL — `ReadTool.run()` doesn't accept a `pages` parameter yet, and has no `.pdf` branch.

- [ ] **Step 4: Commit**

```bash
git add tests/test_read_tool.py
git commit -m "test: add failing tests for ReadTool PDF integration"
```

---

### Task 9: Integrate PDF conversion into `ReadTool.run()`

**Files:**
- Modify: `tools/read.py`

- [ ] **Step 1: Add the import**

At the top of `tools/read.py`, after the existing imports, add:

```python
from tools._pdf_convert import convert_pdf, select_pages
```

- [ ] **Step 2: Update the tool description**

Replace the existing `description` string in `ReadTool`:

```python
    description = (
        "Read the contents of a file. Supports all text files (any extension) — "
        "attempts UTF-8 decoding. Defaults to first 2000 lines. "
        ".docx, .xlsx, and .pptx files are automatically converted to markdown "
        "text before being read. "
        "Use offset/limit for large files. Accepts both relative paths "
        "(resolved from the project root) and absolute paths. "
        "Output uses `cat -n` style: each line is prefixed with its 1-indexed "
        "line number followed by a tab — the number is not part of the file content. "
        "For large-scale codebase exploration, prefer `explore_files`."
    )
```

with:

```python
    description = (
        "Read the contents of a file. Supports all text files (any extension) — "
        "attempts UTF-8 decoding. Defaults to first 2000 lines. "
        ".docx, .xlsx, and .pptx files are automatically converted to markdown "
        "text before being read. "
        ".pdf files are converted to markdown via docling (with high-fidelity table "
        "extraction); use the optional `pages` parameter to select specific pages. "
        "Use offset/limit for large files. Accepts both relative paths "
        "(resolved from the project root) and absolute paths. "
        "Output uses `cat -n` style: each line is prefixed with its 1-indexed "
        "line number followed by a tab — the number is not part of the file content. "
        "For large-scale codebase exploration, prefer `explore_files`."
    )
```

- [ ] **Step 3: Add the `pages` parameter to `_parameters`**

Replace the existing `_parameters` dict:

```python
    _parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read (relative to project root, or absolute)"},
            "offset": {"type": "integer", "description": "Line number to start reading from (1-indexed)"},
            "limit": {"type": "integer", "description": "Maximum number of lines to read"},
        },
        "required": ["path"],
    }
```

with:

```python
    _parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read (relative to project root, or absolute)"},
            "offset": {"type": "integer", "description": "Line number to start reading from (1-indexed)"},
            "limit": {"type": "integer", "description": "Maximum number of lines to read"},
            "pages": {
                "type": "string",
                "description": (
                    "Page range for PDF files (e.g. '1-5', '3', '10-12,15'). "
                    "Only applicable to PDFs. Selects which pages of the converted "
                    "markdown to return. Omit to return all pages."
                ),
            },
        },
        "required": ["path"],
    }
```

- [ ] **Step 4: Rewrite `run()` to add the PDF branch and `pages` parameter**

Replace the entire `run` method:

```python
    def run(self, path: str, offset: int = 1, limit: int = 2000) -> str | list:
```

with:

```python
    def run(
        self,
        path: str,
        offset: int = 1,
        limit: int = 2000,
        pages: str | None = None,
    ) -> str | list:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)

        ext = p.suffix.lower()

        if pages is not None and ext != ".pdf":
            return "Error: 'pages' parameter is only supported for PDF files."

        # ── Blocked file type gate ────────────────────────────────────────
        if ext in _BLOCKED_EXTS:
            return (
                f"Error: Cannot read file type '{ext}'. This file type is not "
                f"currently supported by the read tool. If this file type "
                f"should be supported, update _BLOCKED_EXTS in tools/read.py."
            )
        # ──────────────────────────────────────────────────────────────────

        header = None

        if ext == ".pdf":
            try:
                md_text, cache_path = convert_pdf(p, self.cwd)
            except Exception as e:
                return f"Error: Could not convert '{p.name}': {e}"

            total_pages = md_text.count("<!-- Page ")
            if pages:
                md_text = select_pages(md_text, pages)

            lines = md_text.splitlines()
            header = f"[PDF: {p.name} | {total_pages} pages | cached: {cache_path}"
            if pages:
                header += f" | showing pages {pages}"
            header += "]"

        elif ext in _MARKITDOWN_EXTS:
            try:
                text = _convert_document(p)
            except Exception as e:
                return f"Error: Could not convert '{p.name}': {e}"
            lines = text.splitlines()

        else:
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                return (
                    f"Error: Cannot read '{p.name}' as text. The file appears "
                    f"to be binary or uses an encoding other than UTF-8."
                )

        start = max(0, offset - 1)
        selected = lines[start : start + limit]
        numbered = "\n".join(
            f"{i:6d}\t{line}" for i, line in enumerate(selected, start + 1)
        )

        if header:
            return f"{header}\n{numbered}"
        return numbered
```

- [ ] **Step 5: Run all ReadTool tests**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py -v`

Expected: All tests PASS — the 7 existing DOCX/XLSX/PPTX tests, the 9 helper tests, the 4 detection tests, the 7 pipeline tests, and the 6 integration tests (33 total).

- [ ] **Step 6: Commit**

```bash
git add tools/read.py
git commit -m "feat: ReadTool converts PDF to markdown via docling with pages parameter and cache"
```

---

### Task 10: Full regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `conda run -n dagi python -m pytest tests/ -q --ignore=tests/dagi_eval`

Expected: All tests pass, no regressions. The new PDF tests add ~33 tests to the suite.

- [ ] **Step 2 (optional): Smoke test with a real PDF**

This step requires `docling` and `pymupdf` actually installed. It is optional and does not block completion of this plan.

```bash
conda run -n dagi pip install docling pymupdf
```

Then:

```bash
conda run -n dagi python -c "from pathlib import Path; from tools.read import ReadTool; t = ReadTool(cwd=Path('.'), allowed_roots=[Path('.').resolve()]); print(t.run(path='<path-to-a-real-pdf>')[:500])"
```

Expected: A metadata header line followed by line-numbered markdown reflecting the PDF content (headings, paragraphs, tables with pipe-table syntax).

---

### Task 11: Update project documentation

**Files:**
- Modify: `README.md`
- Modify: `TODO.md`
- Modify: `AGENTS.md` (via the `update-project-context` skill)

- [ ] **Step 1: Update the Tools table in `README.md`**

In `README.md`, find the `read` tool row in the `### Tools` table (around line 562) and replace:

```
| `read` | Read a text file (paginated), or a `.docx`/`.xlsx`/`.pptx` document (auto-converted to markdown via `markitdown`), or image (base64). Pass `path`, optional `offset`/`limit` |
```

with:

```
| `read` | Read a text file (paginated), `.docx`/`.xlsx`/`.pptx` (markdown via `markitdown`), `.pdf` (markdown via `docling` with table detection; scanned PDFs OCR'd via `ocrmypdf`; results cached in `.dagi/pdf_cache/`). Pass `path`, optional `offset`/`limit`, optional `pages` (PDF only, e.g. `'1-5'`) |
```

- [ ] **Step 2: Update the PDF backlog item in `TODO.md` to Completed**

In `TODO.md`, find the PDF backlog item under `### 🟢 Features` (search for `**PDF reading support for \`ReadTool\`**`) and delete it:

```markdown
- **PDF reading support for `ReadTool`** · `priority:medium` · `effort:S`
  - DOCX/XLSX/PPTX support shipped 2026-07-18 (see Completed) via `markitdown`. PDF was deliberately deferred from that work — `markitdown`'s PDF backend (hybrid `pdfplumber`/`pdfminer.six`) has no OCR for scanned pages and documented table-fidelity gaps on complex tables. Needs its own design pass to decide on an OCR/quality bar (plain `markitdown` vs. a heavier layout-aware tool like `docling`/`marker`) before implementing.
  - **Source:** `_todo/todo_2026-06-19.md` D1
```

Then add this entry at the top of the `## Completed` section (above the existing most-recent entry):

```markdown
- **`ReadTool` reads PDF documents (converted to markdown via docling)** · `done` · `2026-07-18`
  - **Problem:** `ReadTool` had no PDF support — PDFs were attempted as UTF-8 text (garbage) or blocked. The prior DOCX/XLSX/PPTX work (also 2026-07-18) deliberately excluded PDF because `markitdown`'s PDF backend had no OCR and collapsed complex tables.
  - **Fix:** New `tools/_pdf_convert.py` module implements a dual pipeline: digital-native PDFs go through `docling` (IBM's deep-learning converter with TableFormer for high-fidelity table extraction including merged/split cells); scanned PDFs are first OCR'd via `ocrmypdf` (tesseract-based, injects invisible text layer at x,y coordinates) then passed through the same docling pipeline. Detection uses `pymupdf` to probe first 3 pages for extractable text (< 50 chars = scanned). Results are cached in `.dagi/pdf_cache/` keyed by SHA-256 of PDF content — repeat reads are instant. New `pages` parameter (e.g. `'1-5,10'`) filters output by `<!-- Page N -->` markers. Output includes a metadata header with cache path for LLM reference. All four dependencies (`docling`, `pymupdf`, `ocrmypdf`, `tesseract`) are optional with graceful degradation.
  - **Test:** `tests/test_read_tool.py` (~33 tests total including prior DOCX/XLSX/PPTX tests) — all via faked modules (`sys.modules` injection), no real PDF fixtures. Covers: page-spec parsing, page selection, scanned-vs-digital detection, digital and scanned conversion pipelines, cache hit/miss/invalidation, dependency degradation, ReadTool integration with pages parameter, error messages. Full suite `pytest tests/ -q --ignore=tests/dagi_eval` — no regressions.
  - Spec: `docs/superpowers/specs/2026-07-18-read-tool-pdf-support-design.md`. Plan: `docs/superpowers/plans/2026-07-18-read-tool-pdf-support.md`.
```

- [ ] **Step 3: Refresh `AGENTS.md`**

Invoke the `update-project-context` skill to refresh `AGENTS.md` — specifically the Key Files & Directories table (add `tools/_pdf_convert.py`), Notes & Terms (add `_PDF_CACHE_DIR`, `convert_pdf`, `is_scanned_pdf`), and the comment about `pdf` in the `_BLOCKED_EXTS` line in `tools/read.py`.

- [ ] **Step 4: Commit**

```bash
git add README.md TODO.md AGENTS.md
git commit -m "docs: record ReadTool PDF support in README/TODO/AGENTS"
```
