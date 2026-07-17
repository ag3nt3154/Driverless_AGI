# Shared Content-Addressed Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract a shared content-addressed cache module (`tools/_hash_cache.py`) and rewire both `tools/_pdf_convert.py` and `tools/output_filter.py` to use it, storing cache entries at `<project_root>/.dagi/hash_cache/{pdf,tool_output}/<sha256>.<ext>` instead of two separate, inconsistent schemes.

**Architecture:** One new module exposes `cache_path()` (hash → path, creates dir) and `get_or_compute()` (cache hit → read; miss → call a caller-supplied closure, write, return). `_pdf_convert.py`'s `convert_pdf()` and `output_filter.py`'s `filter_tool_output()` both call `get_or_compute()` instead of their own ad-hoc hashing/tempfile logic. `agent/loop.py`'s call site passes the project root directly instead of a precomputed temp-dir path.

**Tech Stack:** Python, `hashlib`, `pathlib`, pytest (existing test patterns — `tmp_path` fixture, `sys.modules` monkeypatching for optional deps).

---

## Reference: Design Spec

Full rationale in [docs/superpowers/specs/2026-07-18-shared-hash-cache-design.md](../specs/2026-07-18-shared-hash-cache-design.md). Read it before starting if anything below is unclear.

---

### Task 1: Create the shared hash-cache module

**Files:**
- Create: `tools/_hash_cache.py`
- Test: `tests/test_hash_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_hash_cache.py — Unit tests for tools/_hash_cache.py."""
from __future__ import annotations

import hashlib

from tools._hash_cache import cache_path, get_or_compute


class TestCachePath:
    def test_returns_path_under_hash_cache_subdir(self, tmp_path):
        path, _ = cache_path(b"hello", "pdf", "md", tmp_path)
        assert path.parent == tmp_path / ".dagi" / "hash_cache" / "pdf"

    def test_filename_is_sha256_hex_plus_ext(self, tmp_path):
        path, content_hash = cache_path(b"hello", "pdf", "md", tmp_path)
        assert content_hash == hashlib.sha256(b"hello").hexdigest()
        assert path.name == f"{content_hash}.md"

    def test_creates_subdir(self, tmp_path):
        cache_path(b"hello", "tool_output", "txt", tmp_path)
        assert (tmp_path / ".dagi" / "hash_cache" / "tool_output").is_dir()

    def test_different_keys_different_paths(self, tmp_path):
        path1, _ = cache_path(b"aaa", "pdf", "md", tmp_path)
        path2, _ = cache_path(b"bbb", "pdf", "md", tmp_path)
        assert path1 != path2

    def test_same_key_same_path(self, tmp_path):
        path1, _ = cache_path(b"aaa", "pdf", "md", tmp_path)
        path2, _ = cache_path(b"aaa", "pdf", "md", tmp_path)
        assert path1 == path2


class TestGetOrCompute:
    def test_cache_miss_calls_compute_and_writes(self, tmp_path):
        calls = []

        def compute():
            calls.append(1)
            return "computed text"

        text, path = get_or_compute(b"key1", "pdf", "md", tmp_path, compute)

        assert text == "computed text"
        assert len(calls) == 1
        assert path.read_text(encoding="utf-8") == "computed text"

    def test_cache_hit_skips_compute(self, tmp_path):
        calls = []

        def compute():
            calls.append(1)
            return "computed text"

        get_or_compute(b"key2", "pdf", "md", tmp_path, compute)  # populates cache
        text, path = get_or_compute(b"key2", "pdf", "md", tmp_path, compute)  # hit

        assert text == "computed text"
        assert len(calls) == 1  # compute only called once, on the miss

    def test_returns_cache_path(self, tmp_path):
        text, path = get_or_compute(b"key3", "tool_output", "txt", tmp_path, lambda: "x")
        expected_path, _ = cache_path(b"key3", "tool_output", "txt", tmp_path)
        assert path == expected_path

    def test_writes_lf_only(self, tmp_path):
        text, path = get_or_compute(b"key4", "pdf", "md", tmp_path, lambda: "line1\nline2")
        raw = path.read_bytes()
        assert b"\r\n" not in raw
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_hash_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools._hash_cache'`

- [ ] **Step 3: Implement the module**

```python
"""tools/_hash_cache.py — content-addressed cache shared across read-tool subsystems."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

_HASH_CACHE_DIR = ".dagi/hash_cache"


def cache_path(key: bytes, subdir: str, ext: str, project_root: Path) -> tuple[Path, str]:
    """Return (file_path, hex_hash) for a cache entry. Creates the subdir if missing."""
    content_hash = hashlib.sha256(key).hexdigest()
    cache_dir = Path(project_root) / _HASH_CACHE_DIR / subdir
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{content_hash}.{ext}", content_hash


def get_or_compute(
    key: bytes,
    subdir: str,
    ext: str,
    project_root: Path,
    compute: Callable[[], str],
) -> tuple[str, Path]:
    """Return cached text for `key`, computing (and caching) on a miss.

    `compute` is only called on a cache miss -- callers with expensive derivations
    (e.g. PDF conversion) can defer that work to this closure.
    """
    path, _ = cache_path(key, subdir, ext, project_root)
    if path.exists():
        return path.read_text(encoding="utf-8"), path
    text = compute()
    path.write_text(text, encoding="utf-8", newline="\n")
    return text, path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_hash_cache.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/_hash_cache.py tests/test_hash_cache.py
git commit -m "feat: add shared content-addressed hash cache module"
```

---

### Task 2: Rewire PDF conversion onto the shared cache

**Files:**
- Modify: `tools/_pdf_convert.py`
- Modify: `tests/test_read_tool.py:289,379`

- [ ] **Step 1: Update the existing tests to expect the new cache location**

In `tests/test_read_tool.py`, change line 289 from:

```python
        assert cache_path.parent.name == "pdf_cache"
```

to:

```python
        assert cache_path.parent == tmp_path / ".dagi" / "hash_cache" / "pdf"
```

And change line 379 from:

```python
        cache_dir = tmp_path / ".dagi" / "pdf_cache"
```

to:

```python
        cache_dir = tmp_path / ".dagi" / "hash_cache" / "pdf"
```

- [ ] **Step 2: Run tests to verify they fail against the current implementation**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py::TestConvertPdf -v`
Expected: FAIL — `test_digital_pdf_returns_markdown_and_cache_path` and
`test_intermediate_ocr_pdf_is_cleaned_up` fail because `convert_pdf` still writes to
`.dagi/pdf_cache/`, not `.dagi/hash_cache/pdf/`.

- [ ] **Step 3: Rewrite `convert_pdf()` to use the shared cache**

In `tools/_pdf_convert.py`, replace the imports and the block from `_PDF_CACHE_DIR` (line 51)
through the end of `convert_pdf()` (line 115):

```python
from tools._hash_cache import cache_path, get_or_compute


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


def convert_pdf(pdf_path: Path, project_root: Path) -> tuple[str, Path]:
    """Convert a PDF to markdown, using the shared hash cache.

    Returns (markdown_text, cache_file_path).
    """
    key = pdf_path.read_bytes()

    def compute() -> str:
        cache_dir = cache_path(key, "pdf", "md", project_root)[0].parent
        if is_scanned_pdf(pdf_path):
            return _convert_pdf_scanned(pdf_path, cache_dir)
        return _convert_pdf_digital(pdf_path)

    return get_or_compute(key, "pdf", "md", project_root, compute)
```

Note: `_convert_pdf_digital` and `_convert_pdf_scanned` are unchanged in this diff — only
shown above for placement context. Only the import line and everything from
`_PDF_CACHE_DIR = ...` onward actually changes: `_PDF_CACHE_DIR` and `_get_pdf_cache_path()`
are deleted, `convert_pdf()` is rewritten as shown.

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py::TestIsScannedPdf tests/test_read_tool.py::TestConvertPdf -v`
Expected: PASS (all tests in both classes)

- [ ] **Step 5: Commit**

```bash
git add tools/_pdf_convert.py tests/test_read_tool.py
git commit -m "refactor: rewire PDF conversion cache onto shared hash cache module"
```

---

### Task 3: Rewire tool-output filtering onto the shared cache

**Files:**
- Modify: `tools/output_filter.py`
- Modify: `tests/test_output_filter.py`

- [ ] **Step 1: Update the existing tests to expect the new cache location and API**

In `tests/test_output_filter.py`, apply these changes:

Replace the `test_short_string_no_file_written` test (line 24-26):

```python
    def test_short_string_no_file_written(self, tmp_path):
        filter_tool_output("short", _RESERVE, tmp_path)
        cache_dir = tmp_path / ".dagi" / "hash_cache" / "tool_output"
        assert not cache_dir.exists() or list(cache_dir.iterdir()) == []
```

Replace `test_temp_file_written_with_full_content` (line 78-83):

```python
    def test_temp_file_written_with_full_content(self, tmp_path):
        large = self._large()
        filter_tool_output(large, _RESERVE, tmp_path)
        cache_dir = tmp_path / ".dagi" / "hash_cache" / "tool_output"
        files = list(cache_dir.iterdir())
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == large
```

Replace `test_temp_file_has_correct_prefix_and_suffix` (line 85-89) — the random-prefix
scheme is gone, so this now asserts the hash-named scheme instead:

```python
    def test_cached_file_is_sha256_named(self, tmp_path):
        import hashlib
        large = self._large()
        filter_tool_output(large, _RESERVE, tmp_path)
        cache_dir = tmp_path / ".dagi" / "hash_cache" / "tool_output"
        files = list(cache_dir.iterdir())
        expected_hash = hashlib.sha256(large.encode("utf-8")).hexdigest()
        assert files[0].name == f"{expected_hash}.txt"
```

Add a new dedup test to `TestFiltering`:

```python
    def test_identical_output_reuses_same_cache_file(self, tmp_path):
        large = self._large()
        filter_tool_output(large, _RESERVE, tmp_path)
        filter_tool_output(large, _RESERVE, tmp_path)
        cache_dir = tmp_path / ".dagi" / "hash_cache" / "tool_output"
        files = list(cache_dir.iterdir())
        assert len(files) == 1  # second call reused the first's cache file
```

In `TestErrorHandling`, update the patch targets from `tools.output_filter.Path.*` to
`tools._hash_cache.Path.*` (line 109, 116) since `mkdir`/`write_text` now happen inside
`_hash_cache.py`:

```python
    def test_mkdir_failure_returns_original(self, tmp_path):
        bad_dir = tmp_path / "no_perms"
        with patch("tools._hash_cache.Path.mkdir", side_effect=OSError("permission denied")):
            large = "z" * (_RESERVE * 4 + 1)
            ctx, full = filter_tool_output(large, _RESERVE, bad_dir)
        assert ctx == large   # unfiltered pass-through
        assert full == large

    def test_write_failure_returns_original(self, tmp_path):
        with patch("tools._hash_cache.Path.write_text", side_effect=OSError("disk full")):
            large = "z" * (_RESERVE * 4 + 1)
            ctx, full = filter_tool_output(large, _RESERVE, tmp_path)
        assert ctx == large
```

And update `test_zero_reserve_tokens_skips_filtering` (line 121-125) — the kwarg is renamed:

```python
    def test_zero_reserve_tokens_skips_filtering(self, tmp_path):
        large = "z" * 9999
        ctx, full = filter_tool_output(large, reserve_tokens=0, project_root=tmp_path)
        assert ctx == large
        cache_dir = tmp_path / ".dagi" / "hash_cache" / "tool_output"
        assert not cache_dir.exists() or list(cache_dir.iterdir()) == []
```

- [ ] **Step 2: Run tests to verify they fail against the current implementation**

Run: `conda run -n dagi python -m pytest tests/test_output_filter.py -v`
Expected: FAIL — several tests fail (old tempfile-based paths/names, `temp_dir` kwarg no
longer matching, patch targets pointing at a module that no longer does the writing).

- [ ] **Step 3: Rewrite `filter_tool_output()` to use the shared cache**

Replace the full contents of `tools/output_filter.py`:

```python
"""
tools/output_filter.py — Filter large tool outputs before they enter LLM context.

If a tool result exceeds the token threshold, the full output is saved to the shared
hash cache and a truncated preview + pointer is placed in context instead. This prevents
context-window overflow caused by unexpectedly large tool outputs (grep on a huge
codebase, bash with verbose output, read on a multi-MB file, etc.).

Public API
----------
filter_tool_output(result, reserve_tokens, project_root) -> (context_result, full_str)
"""
from __future__ import annotations

import json
from pathlib import Path

from tools._hash_cache import get_or_compute

# Same heuristic used by compact.py — avoids adding a tokeniser dependency.
_CHARS_PER_TOKEN = 4


def _serialise(result: str | list) -> str:
    """Convert a raw dispatch result to a flat string for size estimation."""
    if isinstance(result, str):
        return result
    return "__list__:" + json.dumps(result)


def filter_tool_output(
    result: str | list,
    reserve_tokens: int,
    project_root: Path,
) -> tuple[str | list, str]:
    """
    Filter a tool result before it enters LLM context.

    Parameters
    ----------
    result        : Raw value returned by registry.dispatch() after sentinel handling.
    reserve_tokens: Token budget threshold from AgentConfig (same field used for
                    compaction). Results >= this many estimated tokens are filtered.
    project_root  : Project root directory. The shared hash cache lives at
                    `<project_root>/.dagi/hash_cache/tool_output/`, created automatically.

    Returns
    -------
    (context_result, full_str)
        context_result — filtered value for _messages and TUI callback.
                         Same type as `result` when not filtered; always str when filtered.
        full_str       — full serialised result for JSONL tracker (never truncated).
    """
    full_str = _serialise(result)

    # Guard: zero/negative reserve means compaction is disabled; skip filtering too.
    if reserve_tokens <= 0:
        return result, full_str

    estimated_tokens = len(full_str) // _CHARS_PER_TOKEN
    if estimated_tokens < reserve_tokens:
        return result, full_str  # pass-through — small enough to enter context raw

    # ── Result is large: cache it, build truncated context message ──
    try:
        _, tmp_path = get_or_compute(
            full_str.encode("utf-8"), "tool_output", "txt", project_root, lambda: full_str
        )
    except OSError:
        # Fail open: if we can't write the file, return the original result
        # unfiltered. The caller (AgentLoop) will emit a warning separately.
        return result, full_str

    preview_chars = (reserve_tokens // 2) * _CHARS_PER_TOKEN
    preview = full_str[:preview_chars]

    context_result = (
        f"{preview}\n\n"
        f"--- OUTPUT TRUNCATED ---\n"
        f"Full output saved to: {tmp_path}\n"
        f"Tool output is very large (~{estimated_tokens:,} tokens estimated). "
        f"Read it chunk by chunk using the read tool with the offset and limit parameters."
    )
    return context_result, full_str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_output_filter.py -v -k "not TestLoopIntegration"`
Expected: PASS (`TestLoopIntegration` is addressed in Task 4 — it exercises `agent/loop.py`,
which hasn't been updated yet)

- [ ] **Step 5: Commit**

```bash
git add tools/output_filter.py tests/test_output_filter.py
git commit -m "refactor: rewire tool-output filter cache onto shared hash cache module"
```

---

### Task 4: Update the `agent/loop.py` call site

**Files:**
- Modify: `agent/loop.py:309`, `agent/loop.py:666-675`
- Test: `tests/test_output_filter.py::TestLoopIntegration` (no edits expected, used to verify)

- [ ] **Step 1: Remove the now-unused `_filter_temp` attribute**

In `agent/loop.py`, delete line 309:

```python
        self._filter_temp = Path(config.project_path) / ".dagi" / "temp"
```

- [ ] **Step 2: Update the output-filter call site**

In `agent/loop.py`, replace lines 666-675:

```python
                    # ── Output filter ────────────────────────────────────────
                    context_result, full_str = filter_tool_output(
                        result, self.config.reserve_tokens, self._filter_temp
                    )
                    if context_result is not result:
                        # Filtering fired — warn the user via the assistant text stream
                        self.callbacks.on_assistant_text(
                            f"[output filter] Tool result was large and has been truncated. "
                            f"Full output saved to {self._filter_temp}."
                        )
                    # ─────────────────────────────────────────────────────────
```

with:

```python
                    # ── Output filter ────────────────────────────────────────
                    context_result, full_str = filter_tool_output(
                        result, self.config.reserve_tokens, Path(self.config.project_path)
                    )
                    if context_result is not result:
                        # Filtering fired — warn the user via the assistant text stream
                        self.callbacks.on_assistant_text(
                            f"[output filter] Tool result was large and has been truncated. "
                            f"Full output saved under "
                            f"{Path(self.config.project_path) / '.dagi' / 'hash_cache' / 'tool_output'}."
                        )
                    # ─────────────────────────────────────────────────────────
```

- [ ] **Step 3: Run the loop-integration test to verify it still passes**

Run: `conda run -n dagi python -m pytest tests/test_output_filter.py::TestLoopIntegration -v`
Expected: PASS — the test only asserts `"OUTPUT TRUNCATED"` is in the message content,
`"[output filter]"` is in a warning call, and the tracker gets the full string. None of those
assertions depend on the exact warning wording, so no test changes are needed.

- [ ] **Step 4: Run the full test suite to check for regressions**

Run: `conda run -n dagi python -m pytest tests/ -v`
Expected: PASS across the board. If `tests/test_read_tool.py::TestReadToolPdf` fails, that is
pre-existing (unrelated to this plan — `ReadTool.run()`'s PDF branch is not yet wired; see
`docs/superpowers/plans/2026-07-18-read-tool-pdf-support.md`). Confirm any failures there are
unrelated to files touched by this plan (`tools/_hash_cache.py`, `tools/_pdf_convert.py`,
`tools/output_filter.py`, `agent/loop.py`) before treating the run as green.

- [ ] **Step 5: Commit**

```bash
git add agent/loop.py
git commit -m "refactor: point AgentLoop's output filter at project_root instead of a temp-dir path"
```

---

## Self-Review Notes

- **Spec coverage:** `_hash_cache.py` module (Task 1) ✓, PDF rewire (Task 2) ✓, output-filter
  rewire (Task 3) ✓, loop.py call site + removed `_filter_temp` (Task 4) ✓, directory layout
  `.dagi/hash_cache/{pdf,tool_output}/` (Tasks 2+3) ✓, dedup behavior test (Task 3) ✓, no
  eviction added (nothing added — matches spec) ✓, no migration of old dirs (nothing added —
  matches spec) ✓.
- **Out of scope, confirmed:** `ReadTool.run()`'s PDF branch integration is a separate,
  pre-existing in-flight effort — this plan does not touch `tools/read.py`.
