# PDF Parallel Conversion (Map-Reduce) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up `convert_pdf()` for large PDFs by splitting them into page-range chunks, converting chunks in parallel across worker processes, and merging the results back into markdown identical in shape to today's single-process output.

**Architecture:** `convert_pdf()` gains a parallel path gated by a page-count threshold. Worker count is estimated from CPU count, free RAM, and page count, with `worker_ram_gb`/`max_workers` configurable via a new `pdf:` key in `config.yaml`. Splitting uses `fitz` to carve the source PDF into sub-PDFs; a `ProcessPoolExecutor` converts each sub-PDF via the existing (unchanged) per-chunk pipeline functions; results are renumbered and concatenated in the reduce step.

**Tech Stack:** Python `concurrent.futures.ProcessPoolExecutor`, `fitz` (pymupdf), `psutil`, existing `docling`/`ocrmypdf` pipeline functions in `tools/_pdf_convert.py`.

**Reference spec:** `docs/superpowers/specs/2026-07-18-pdf-parallel-conversion-design.md`

---

## File Structure

- **Modify:** `agent/config_loader.py` — add `PdfConfig` dataclass + `load_pdf_config()` (same pattern as existing `TelegramConfig`/`load_telegram_config()`)
- **Modify:** `tools/_pdf_convert.py` — add `_get_page_count`, `_estimate_worker_count`, `_renumber_markers`, `ChunkSpec`, `_split_into_chunks`, `_convert_chunk`, `_convert_pdf_parallel`; wire into `convert_pdf()`
- **Modify:** `requirements.txt` — add `psutil` as a core (required) dependency
- **Modify:** `tests/test_config_loader.py` — tests for `load_pdf_config`
- **Modify:** `tests/test_read_tool.py` — tests for the new `_pdf_convert.py` functions, plus new fake-module helpers (`_install_fake_psutil`, extended `_install_fake_fitz` supporting splitting)
- **Modify:** `README.md`, `TODO.md`, `AGENTS.md` — document the shipped feature

---

### Task 1: `PdfConfig` + `load_pdf_config()` in `agent/config_loader.py`

**Files:**
- Modify: `agent/config_loader.py`
- Test: `tests/test_config_loader.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config_loader.py`:

```python
from agent.config_loader import PdfConfig, load_pdf_config


class TestLoadPdfConfig:
    def test_defaults_when_pdf_key_absent(self, monkeypatch):
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {})
        cfg = load_pdf_config()
        assert cfg == PdfConfig(worker_ram_gb=2.0, max_workers=None)

    def test_overrides_from_config(self, monkeypatch):
        monkeypatch.setattr(
            "agent.config_loader.load_raw_config",
            lambda: {"pdf": {"worker_ram_gb": 4.0, "max_workers": 3}},
        )
        cfg = load_pdf_config()
        assert cfg == PdfConfig(worker_ram_gb=4.0, max_workers=3)

    def test_partial_override_keeps_other_default(self, monkeypatch):
        monkeypatch.setattr(
            "agent.config_loader.load_raw_config",
            lambda: {"pdf": {"max_workers": 5}},
        )
        cfg = load_pdf_config()
        assert cfg.worker_ram_gb == 2.0
        assert cfg.max_workers == 5

    def test_null_pdf_key_uses_defaults(self, monkeypatch):
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {"pdf": None})
        cfg = load_pdf_config()
        assert cfg == PdfConfig(worker_ram_gb=2.0, max_workers=None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_config_loader.py::TestLoadPdfConfig -v`
Expected: FAIL with `ImportError: cannot import name 'PdfConfig'`

- [ ] **Step 3: Implement `PdfConfig` and `load_pdf_config()`**

In `agent/config_loader.py`, add directly after the existing `load_telegram_config()` function (which ends around the line with `return TelegramConfig(bot_token=token)`):

```python
@dataclass
class PdfConfig:
    """PDF parallel-conversion settings loaded from the `pdf:` key in config.yaml."""
    worker_ram_gb: float = 2.0
    max_workers: int | None = None


def load_pdf_config() -> PdfConfig:
    """Return PDF parallel-conversion settings from config.yaml, applying defaults."""
    raw = load_raw_config()
    pdf = raw.get("pdf") or {}
    return PdfConfig(
        worker_ram_gb=pdf.get("worker_ram_gb", 2.0),
        max_workers=pdf.get("max_workers"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_config_loader.py::TestLoadPdfConfig -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/config_loader.py tests/test_config_loader.py
git commit -m "feat: add PdfConfig/load_pdf_config for PDF worker settings"
```

---

### Task 2: Declare `psutil` as a core dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add `psutil` to the Core section**

In `requirements.txt`, add a line after `langchain-openai>=1.2.2` (end of the `# ── Core (required) ──` block, before the blank line that precedes `# ── Windows notifications (TUI) ──`):

```
psutil>=5.9.0                # RAM/CPU introspection — PDF parallel-conversion worker sizing; already required by tests/conftest.py's RAM guard
```

- [ ] **Step 2: Verify it's already importable in the `dagi` env**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -c "import psutil; print(psutil.__version__)"`
Expected: prints a version string (psutil is already installed, since `tests/conftest.py` imports it — this step just confirms no fresh install is needed).

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "docs: declare psutil as a core dependency"
```

---

### Task 3: `_get_page_count()` in `tools/_pdf_convert.py`

**Files:**
- Modify: `tools/_pdf_convert.py`
- Test: `tests/test_read_tool.py`

`_install_fake_fitz` (already in `tests/test_read_tool.py` at line 110) creates fake docs with a fixed `num_pages` and supports `len(doc)`/`doc[idx]`/`doc.close()` — that's already enough to test page counting; no extension needed for this task.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_read_tool.py`, after the `TestIsScannedPdf` class:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestGetPageCount -v`
Expected: FAIL with `ImportError: cannot import name '_get_page_count'`

- [ ] **Step 3: Implement `_get_page_count()`**

In `tools/_pdf_convert.py`, add directly after `is_scanned_pdf()`:

```python
def _get_page_count(pdf_path: Path) -> int:
    """Return the page count of a PDF, or 0 if fitz is unavailable."""
    try:
        import fitz
    except ImportError:
        return 0
    doc = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestGetPageCount -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/_pdf_convert.py tests/test_read_tool.py
git commit -m "feat: add _get_page_count helper to _pdf_convert"
```

---

### Task 4: `_estimate_worker_count()` in `tools/_pdf_convert.py`

**Files:**
- Modify: `tools/_pdf_convert.py`
- Test: `tests/test_read_tool.py`

This task needs a fake `psutil` module and control over `os.cpu_count()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_read_tool.py`, after the `TestGetPageCount` class:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestEstimateWorkerCount -v`
Expected: FAIL with `ImportError: cannot import name '_estimate_worker_count'`

- [ ] **Step 3: Implement `_estimate_worker_count()`**

In `tools/_pdf_convert.py`, add `import os` to the top-level imports and `from agent.config_loader import load_pdf_config`:

```python
from __future__ import annotations

import os
import re
from pathlib import Path

from agent.config_loader import load_pdf_config
from tools._hash_cache import cache_path, get_or_compute
```

Then add, after `_get_page_count()`:

```python
def _estimate_worker_count(page_count: int) -> int:
    """Estimate a safe worker-process count from CPU count, free RAM, and page count.

    page_count caps workers 1:1 -- no point having more workers than pages to split.
    """
    cfg = load_pdf_config()
    caps = [os.cpu_count() or 1, page_count]

    try:
        import psutil
        available_bytes = psutil.virtual_memory().available
        caps.append(int(available_bytes // (cfg.worker_ram_gb * 1024**3)))
    except ImportError:
        pass

    if cfg.max_workers is not None:
        caps.append(cfg.max_workers)

    return max(1, min(caps))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestEstimateWorkerCount -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/_pdf_convert.py tests/test_read_tool.py
git commit -m "feat: add _estimate_worker_count using CPU/RAM/page-count/config caps"
```

---

### Task 5: `_renumber_markers()` in `tools/_pdf_convert.py`

**Files:**
- Modify: `tools/_pdf_convert.py`
- Test: `tests/test_read_tool.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_read_tool.py`, after the `TestEstimateWorkerCount` class:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestRenumberMarkers -v`
Expected: FAIL with `ImportError: cannot import name '_renumber_markers'`

- [ ] **Step 3: Implement `_renumber_markers()`**

In `tools/_pdf_convert.py`, add near the top (after imports, before `parse_page_spec`):

```python
_PAGE_MARKER_RE = re.compile(r"<!-- Page (\d+) -->")
```

Then add, after `_estimate_worker_count()`:

```python
def _renumber_markers(markdown: str, start_offset: int) -> str:
    """Rewrite a chunk's local <!-- Page N --> markers to global page numbers.

    A chunk's docling output numbers pages from 1 within whatever pages it was
    given. start_offset is the chunk's first page number in the original
    document (1-indexed), so local page 1 becomes start_offset.
    """
    def _replace(match: re.Match) -> str:
        local = int(match.group(1))
        return f"<!-- Page {local + start_offset - 1} -->"

    return _PAGE_MARKER_RE.sub(_replace, markdown)
```

Note: `select_pages()` further down in the file has its own local regex
(`re.split(r"(<!-- Page \d+ -->)", markdown)`) — leave it as-is; it doesn't
need to share `_PAGE_MARKER_RE` for this task, and changing it is out of scope.

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestRenumberMarkers -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/_pdf_convert.py tests/test_read_tool.py
git commit -m "feat: add _renumber_markers for chunk-local to global page numbers"
```

---

### Task 6: `ChunkSpec` + `_split_into_chunks()` in `tools/_pdf_convert.py`

**Files:**
- Modify: `tools/_pdf_convert.py`
- Test: `tests/test_read_tool.py`

This task needs the fake `fitz` module extended to support creating and saving
new sub-documents (`fitz.open()` with no path, `insert_pdf()`, `save()`).

- [ ] **Step 1: Extend `_install_fake_fitz` to support splitting**

In `tests/test_read_tool.py`, replace the existing `_install_fake_fitz` function
(starting at line 110) with this extended version that adds split support
while keeping all existing detection behavior identical:

```python
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
```

(This adds `insert_pdf`/`save` to `_FakeDoc` and makes `open()` accept no
arguments to create a fresh empty doc, without changing any existing
detection-test behavior — `_FakeDoc.__len__`/`__getitem__`/`close` are
unchanged, and `fitz.open(path)` with a path still returns the same
page-populated doc as before.)

- [ ] **Step 2: Run the existing PDF test suite to confirm nothing broke**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py -k "Fitz or ScannedPdf or ConvertPdf or PageCount or WorkerCount or RenumberMarkers" -v`
Expected: PASS (all pre-existing tests still pass with the extended fake)

- [ ] **Step 3: Write the failing tests for `_split_into_chunks`**

Add to `tests/test_read_tool.py`, after the `TestRenumberMarkers` class:

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestSplitIntoChunks -v`
Expected: FAIL with `ImportError: cannot import name 'ChunkSpec'`

- [ ] **Step 5: Implement `ChunkSpec` and `_split_into_chunks()`**

In `tools/_pdf_convert.py`, add `from typing import NamedTuple` to imports:

```python
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

from agent.config_loader import load_pdf_config
from tools._hash_cache import cache_path, get_or_compute
```

Then add, after `_renumber_markers()`:

```python
class ChunkSpec(NamedTuple):
    """One page-range chunk of a PDF being split for parallel conversion."""
    path: Path
    start_offset: int   # this chunk's first page number in the original doc (1-indexed)
    chunk_index: int    # 0-indexed position among sibling chunks, for reduce-step ordering


def _split_into_chunks(pdf_path: Path, cache_dir: Path, worker_count: int) -> list[ChunkSpec]:
    """Split a PDF into worker_count page-range sub-PDFs, written into cache_dir."""
    import fitz

    src = fitz.open(str(pdf_path))
    total_pages = len(src)
    base, extra = divmod(total_pages, worker_count)

    chunks: list[ChunkSpec] = []
    start = 0
    for i in range(worker_count):
        size = base + (1 if i < extra else 0)
        if size == 0:
            continue
        end = start + size - 1  # inclusive, 0-indexed
        chunk_doc = fitz.open()
        chunk_doc.insert_pdf(src, from_page=start, to_page=end)
        chunk_path = cache_dir / f"{pdf_path.stem}_chunk{i}.pdf"
        chunk_doc.save(str(chunk_path))
        chunk_doc.close()
        chunks.append(ChunkSpec(path=chunk_path, start_offset=start + 1, chunk_index=i))
        start = end + 1

    src.close()
    return chunks
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestSplitIntoChunks -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add tools/_pdf_convert.py tests/test_read_tool.py
git commit -m "feat: add ChunkSpec and _split_into_chunks for PDF page-range splitting"
```

---

### Task 7: `_convert_chunk()` in `tools/_pdf_convert.py`

**Files:**
- Modify: `tools/_pdf_convert.py`
- Test: `tests/test_read_tool.py`

`_convert_chunk` must be a top-level (module-scope) function — it's the
callable dispatched to `ProcessPoolExecutor`, which requires picklable
targets, not closures or bound methods.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_read_tool.py`, after the `TestSplitIntoChunks` class:

```python
from tools._pdf_convert import _convert_chunk


class TestConvertChunk:
    def test_digital_chunk_renumbered(self, tmp_path, monkeypatch):
        md = "<!-- Page 1 -->\n# Chunk Title\n\nBody."
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
        md = "<!-- Page 1 -->\n# OCR Chunk\n\nBody."
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestConvertChunk -v`
Expected: FAIL with `ImportError: cannot import name '_convert_chunk'`

- [ ] **Step 3: Implement `_convert_chunk()`**

In `tools/_pdf_convert.py`, add after `_split_into_chunks()`:

```python
def _convert_chunk(
    chunk_path: Path, is_scanned: bool, start_offset: int, chunk_index: int, cache_dir: Path
) -> tuple[int, str]:
    """Convert one page-range chunk and renumber its markers to global page numbers.

    Top-level function (not a closure/method) -- this is the callable dispatched
    to ProcessPoolExecutor, which requires picklable targets.
    """
    if is_scanned:
        markdown = _convert_pdf_scanned(chunk_path, cache_dir)
    else:
        markdown = _convert_pdf_digital(chunk_path)
    return chunk_index, _renumber_markers(markdown, start_offset)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestConvertChunk -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/_pdf_convert.py tests/test_read_tool.py
git commit -m "feat: add _convert_chunk, the per-chunk conversion+renumber unit"
```

---

### Task 8: `_convert_pdf_parallel()` orchestrator in `tools/_pdf_convert.py`

**Files:**
- Modify: `tools/_pdf_convert.py`
- Test: `tests/test_read_tool.py`

Tests stub `ProcessPoolExecutor` with `concurrent.futures.ThreadPoolExecutor`.
Threads share the test process's `sys.modules`, so the fake `fitz`/`docling`/
`ocrmypdf` modules installed via `monkeypatch.setitem` are visible to
submitted work — a real `ProcessPoolExecutor` would spawn child processes
with their own fresh `sys.modules` and would never see the fakes.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_read_tool.py`, after the `TestConvertChunk` class:

```python
import concurrent.futures

from tools._pdf_convert import _convert_pdf_parallel


class TestConvertPdfParallel:
    def test_merges_chunks_in_order(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools._pdf_convert.ProcessPoolExecutor",
            concurrent.futures.ThreadPoolExecutor,
        )
        _install_fake_fitz(monkeypatch, num_pages=10)
        _install_fake_docling(monkeypatch, markdown="<!-- Page 1 -->\nchunk-content")
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
        _install_fake_docling(monkeypatch, markdown="<!-- Page 1 -->\ncontent")
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

        class _FailingConverter:
            def convert(self, path):
                raise RuntimeError("docling exploded")

        fake_dc_module = type(sys)("docling.document_converter")
        fake_dc_module.DocumentConverter = _FailingConverter
        fake_docling = type(sys)("docling")
        fake_docling.document_converter = fake_dc_module
        monkeypatch.setitem(sys.modules, "docling", fake_docling)
        monkeypatch.setitem(sys.modules, "docling.document_converter", fake_dc_module)

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"fake pdf bytes")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with pytest.raises(RuntimeError, match="docling exploded"):
            _convert_pdf_parallel(pdf, cache_dir, False, page_count=10, worker_count=2)

        leftover_chunks = list(cache_dir.glob("*_chunk*.pdf"))
        assert leftover_chunks == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestConvertPdfParallel -v`
Expected: FAIL with `ImportError: cannot import name '_convert_pdf_parallel'`

- [ ] **Step 3: Implement `_convert_pdf_parallel()`**

In `tools/_pdf_convert.py`, add `from concurrent.futures import ProcessPoolExecutor, as_completed` to imports:

```python
from __future__ import annotations

import os
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple

from agent.config_loader import load_pdf_config
from tools._hash_cache import cache_path, get_or_compute
```

Then add, after `_convert_chunk()`:

```python
def _convert_pdf_parallel(
    pdf_path: Path, cache_dir: Path, scanned: bool, page_count: int, worker_count: int
) -> str:
    """Split, convert, and merge a PDF's pages using a worker process pool.

    Any chunk failure cancels remaining work and propagates the error --
    no partial markdown is ever returned. Temp chunk PDFs are always cleaned up.
    """
    chunks = _split_into_chunks(pdf_path, cache_dir, worker_count)
    results: dict[int, str] = {}
    try:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _convert_chunk, chunk.path, scanned, chunk.start_offset,
                    chunk.chunk_index, cache_dir,
                ): chunk
                for chunk in chunks
            }
            try:
                for future in as_completed(futures):
                    idx, markdown = future.result()
                    results[idx] = markdown
            except Exception:
                for future in futures:
                    future.cancel()
                raise
    finally:
        for chunk in chunks:
            chunk.path.unlink(missing_ok=True)

    return "".join(results[i] for i in sorted(results))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestConvertPdfParallel -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/_pdf_convert.py tests/test_read_tool.py
git commit -m "feat: add _convert_pdf_parallel map-reduce orchestrator"
```

---

### Task 9: Wire parallel path into `convert_pdf()`

**Files:**
- Modify: `tools/_pdf_convert.py`
- Test: `tests/test_read_tool.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_read_tool.py`, inside the existing `TestConvertPdf` class
(after its last existing test method):

```python
    def test_large_pdf_uses_parallel_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools._pdf_convert.ProcessPoolExecutor",
            concurrent.futures.ThreadPoolExecutor,
        )
        monkeypatch.setattr("os.cpu_count", lambda: 4)
        _install_fake_psutil(monkeypatch, available_bytes=100 * 1024**3)
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {})
        _install_fake_fitz(monkeypatch, chars_per_page=500, num_pages=20)
        _install_fake_docling(monkeypatch, markdown="<!-- Page 1 -->\ncontent")
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
        _install_fake_docling(monkeypatch, markdown="<!-- Page 1 -->\nsmall doc content")
        pdf = tmp_path / "small.pdf"
        pdf.write_bytes(b"fake small pdf bytes")

        text, _ = convert_pdf(pdf, tmp_path)

        assert "small doc content" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestConvertPdf::test_large_pdf_uses_parallel_path tests/test_read_tool.py::TestConvertPdf::test_small_pdf_stays_single_process -v`
Expected: FAIL — the large-PDF test fails because `convert_pdf()` still always
uses the single-process path (assertion on `"<!-- Page 6 -->"` fails, since
today's fake docling always returns the same single-chunk markdown starting at
page 1 regardless of doc size). The small-PDF test passes already (no
behavior change needed there) — confirm it stays green after Step 3 too.

- [ ] **Step 3: Wire `_convert_pdf_parallel` into `convert_pdf()`**

In `tools/_pdf_convert.py`, add the threshold constant near the top (after
`_SCANNED_CHAR_THRESHOLD`):

```python
PDF_PARALLEL_MIN_PAGES = 8   # below this, single-process path -- not config-exposed
```

Then replace the body of `convert_pdf()`'s `compute()` closure:

```python
def convert_pdf(pdf_path: Path, project_root: Path) -> tuple[str, Path]:
    """Convert a PDF to markdown, using the shared hash cache.

    Returns (markdown_text, cache_file_path).
    """
    key = pdf_path.read_bytes()

    def compute() -> str:
        cache_dir = cache_path(key, "pdf", "md", project_root)[0].parent
        scanned = is_scanned_pdf(pdf_path)
        page_count = _get_page_count(pdf_path)
        worker_count = (
            _estimate_worker_count(page_count)
            if page_count > PDF_PARALLEL_MIN_PAGES
            else 1
        )
        if worker_count <= 1:
            return (
                _convert_pdf_scanned(pdf_path, cache_dir)
                if scanned
                else _convert_pdf_digital(pdf_path)
            )
        return _convert_pdf_parallel(pdf_path, cache_dir, scanned, page_count, worker_count)

    return get_or_compute(key, "pdf", "md", project_root, compute)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest tests/test_read_tool.py::TestConvertPdf -v`
Expected: PASS (all `TestConvertPdf` tests, including the 2 new ones)

- [ ] **Step 5: Commit**

```bash
git add tools/_pdf_convert.py tests/test_read_tool.py
git commit -m "feat: wire parallel map-reduce path into convert_pdf()"
```

---

### Task 10: Full regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -m pytest -v`
Expected: PASS, zero failures, zero regressions. Note the final test count
(was 426 before this plan; this plan adds tests from Tasks 1, 3, 4, 5, 6, 7,
8, 9 — roughly 4 + 2 + 6 + 4 + 4 + 2 + 3 + 2 = 27 new tests, so expect ~453).

- [ ] **Step 2: Sanity-check `tools/_pdf_convert.py` for lint/complexity issues**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -c "import ast; tree = ast.parse(open('tools/_pdf_convert.py').read()); print('OK — parses cleanly')"`
Expected: `OK — parses cleanly`

Manually confirm (per this project's coding standards in `CLAUDE.md`):
functions stay under 100 lines, the file stays under 500 lines, no function
exceeds ~5 positional parameters. `_convert_pdf_parallel` and `_convert_chunk`
are the largest additions — re-read them and split further only if either
has grown unexpectedly large during implementation.

- [ ] **Step 3: Confirm no circular import was introduced**

Run: `& "$env:USERPROFILE\miniconda3\condabin\conda.bat" run -n dagi python -c "import tools._pdf_convert; import agent.tools; print('OK — no circular import')"`
Expected: `OK — no circular import` (this exercises the new
`tools._pdf_convert -> agent.config_loader -> agent.loop` import chain
alongside `agent.tools -> tools.read -> tools._pdf_convert`, which already
existed via `tools.read -> agent.base_tool`).

---

### Task 11: Update project documentation

**Files:**
- Modify: `README.md`
- Modify: `TODO.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update `README.md`**

Find the `read` tool's row/section describing PDF support (added when PDF
support first shipped) and add a note that large PDFs (>8 pages) are now
converted in parallel across multiple worker processes, with `worker_ram_gb`
and `max_workers` configurable under a new `pdf:` key in `config.yaml`.

- [ ] **Step 2: Update `TODO.md`**

Add an entry under `## Completed` documenting: PDF parallel conversion
(map-reduce) shipped, new `pdf:` config.yaml key (`worker_ram_gb`,
`max_workers`), `psutil` added as a core dependency, final test count from
Task 10, and a reference to
`docs/superpowers/specs/2026-07-18-pdf-parallel-conversion-design.md` and
this plan file.

- [ ] **Step 3: Update `AGENTS.md` using the update-project-context skill**

Invoke the `update-project-context` skill to refresh `AGENTS.md`:
- Update the `Key Files & Directories` row for `tools/_pdf_convert.py` to
  mention the parallel map-reduce path (chunk splitting, worker pool,
  renumber/merge).
- Add a row (or extend the existing `agent/config_loader.py` row if one
  exists) noting `PdfConfig`/`load_pdf_config()`.
- Add a `Notes & Terms` entry for the `pdf:` config.yaml key and the
  `PDF_PARALLEL_MIN_PAGES` threshold.
- Note the new `tools -> agent.config_loader` import direction if it's not
  already implied by the existing `tools.read -> agent.base_tool` precedent
  noted in the file.

- [ ] **Step 4: Commit**

```bash
git add README.md TODO.md AGENTS.md
git commit -m "docs: document PDF parallel conversion feature"
```

---

## Self-Review Notes (for the plan author, not a task)

- **Spec coverage:** Detection (unchanged, Task 9 reuses `is_scanned_pdf`
  as-is) / threshold (Task 9) / worker estimate + config (Tasks 1, 4) / map
  (Task 6) / dispatch (Tasks 7, 8) / reduce (Task 8) / failure handling (Task
  8) / integration point (Task 9) / dependencies (Task 2) / testing strategy
  (all tasks use the sys.modules fake pattern + ThreadPoolExecutor stub) /
  scope exclusions (no config for `PDF_PARALLEL_MIN_PAGES` — confirmed Task 9
  keeps it a hardcoded constant; no per-chunk mixed pipelines — confirmed
  `_convert_pdf_parallel` takes a single `scanned` bool applied to every
  chunk; no cache format change — confirmed `convert_pdf()`'s public
  signature and `get_or_compute` call are untouched). All spec sections have
  a corresponding task.
- **Type consistency checked:** `ChunkSpec` fields (`path`, `start_offset`,
  `chunk_index`) match across Tasks 6, 7, 8. `_estimate_worker_count(page_count: int)`
  signature matches its Task 4 definition and Task 9's call site.
  `_convert_chunk(chunk_path, is_scanned, start_offset, chunk_index, cache_dir)`
  parameter order matches between its Task 7 definition and Task 8's
  `executor.submit(...)` call.
