# Shared Content-Addressed Cache — Design Spec

> **Date:** 2026-07-18 | **Status:** Draft | **Author:** Claude-chan + Admiral

---

## Problem

Two independent designs in this codebase both want a content-addressed cache, with duplicated
hashing logic and inconsistent roots:

1. **PDF conversion** (`docs/superpowers/specs/2026-07-18-read-tool-pdf-support-design.md`,
   partially implemented in `tools/_pdf_convert.py`) — caches converted markdown at
   `<project_root>/.dagi/pdf_cache/<sha256(pdf_bytes)>.md`. Not yet wired into `ReadTool.run()`.
2. **Tool output filtering** (`tools/output_filter.py`, live in production) — writes oversized
   tool results to `<project_root>/.dagi/temp/tool_output_<random>.txt` via `tempfile.mkstemp()`.
   Filenames are random, so identical large outputs (e.g. the same verbose `bash` command
   re-run mid-session) get written to disk again on every occurrence. `TODO.md:376` already
   flags the resulting unbounded accumulation (8 files after 2 days of testing).

Both problems are instances of the same pattern: "given some bytes, cache derived content keyed
by a hash of those bytes." Solving them with one shared module avoids duplicated hashing code
and gives tool-output filtering the same dedup benefit the PDF design already has.

## Goal

Introduce `tools/_hash_cache.py`, a single content-addressed cache helper used by both
`tools/_pdf_convert.py` and `tools/output_filter.py`. Both write under
`<project_root>/.dagi/hash_cache/<subdir>/<sha256>.<ext>`.

## Architecture

### New module: `tools/_hash_cache.py`

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

**Design decisions:**
- **`project_root` always, never `DAGI_ROOT`.** Both cache kinds live inside the project being
  worked on, not DAGI's own install directory. This matches the PDF spec's original reasoning
  ("the PDF belongs to the project") and required no change to `agent/loop.py`'s existing
  `self._filter_temp = Path(config.project_path) / ".dagi" / "temp"` — it was already rooted at
  the project path, just pointed at a different subfolder.
- **`compute` is a closure, not a precomputed string.** PDF conversion (docling/OCR) is
  expensive; tool-output text is already in hand. A single `get_or_compute` signature serves
  both: the tool-output caller passes `lambda: full_str` (trivial), the PDF caller passes the
  real conversion pipeline (deferred until a cache miss confirms it's needed).
- **LF-only writes** (`newline="\n"`), matching DAGI's existing EditTool/WriteTool/PDF-cache
  convention.
- **No cache eviction.** Matches the PDF cache design's precedent exactly. Hash-naming already
  eliminates the worst case (repeated identical large outputs no longer multiply on disk), but
  distinct-content entries still accumulate over time. Eviction is deferred as a separate,
  smaller follow-up if it becomes a problem in practice.

### Rewiring `tools/_pdf_convert.py`

`_get_pdf_cache_path()` and `_PDF_CACHE_DIR` are removed. `convert_pdf()` becomes:

```python
def convert_pdf(pdf_path: Path, project_root: Path) -> tuple[str, Path]:
    """Convert a PDF to markdown, using the shared hash cache."""
    key = pdf_path.read_bytes()

    def compute() -> str:
        cache_dir = cache_path(key, "pdf", "md", project_root)[0].parent
        if is_scanned_pdf(pdf_path):
            return _convert_pdf_scanned(pdf_path, cache_dir)
        return _convert_pdf_digital(pdf_path)

    return get_or_compute(key, "pdf", "md", project_root, compute)
```

`_convert_pdf_scanned(pdf_path, cache_dir)` is unchanged internally — it still needs a directory
to write its intermediate OCR'd PDF before cleaning it up. That directory is now
`<project_root>/.dagi/hash_cache/pdf/` instead of `<project_root>/.dagi/pdf_cache/`.

### Rewiring `tools/output_filter.py`

`filter_tool_output`'s third parameter is renamed from `temp_dir: Path` to
`project_root: Path`. The temp-file-writing block:

```python
temp_dir = Path(temp_dir)
temp_dir.mkdir(parents=True, exist_ok=True)
fd, tmp_path = tempfile.mkstemp(dir=temp_dir, prefix="tool_output_", suffix=".txt")
os.close(fd)
Path(tmp_path).write_text(full_str, encoding="utf-8")
```

becomes:

```python
from tools._hash_cache import get_or_compute

try:
    _, tmp_path = get_or_compute(
        full_str.encode("utf-8"), "tool_output", "txt", project_root, lambda: full_str
    )
except OSError:
    return result, full_str  # fail open, same as before
```

`tempfile` and `os` imports are dropped from `output_filter.py` (no longer used). All other
logic (token estimation, threshold, preview slicing, truncation message) is unchanged.

### Call site: `agent/loop.py`

```python
context_result, full_str = filter_tool_output(
    result, self.config.reserve_tokens, Path(self.config.project_path)
)
```

`self._filter_temp` (currently `Path(config.project_path) / ".dagi" / "temp"`, set in
`__init__`) is removed — `get_or_compute` builds the full path internally from `project_root`.
The warning message at the call site (`f"Full output saved to {self._filter_temp}."`) is updated
to reference the actual returned path instead of the removed attribute — it already has access
to `tmp_path` via the tuple `filter_tool_output` returns internally, but since `loop.py` only
receives `context_result`/`full_str` (not the cache path directly), the warning text is
simplified to reference the directory rather than a specific file:
`f"Full output saved under {self.config.project_path}/.dagi/hash_cache/tool_output/."`

## Directory Layout

```
<project_root>/.dagi/hash_cache/
├── pdf/
│   ├── a1b2c3...7890.md
│   └── f9e8d7...1234.md
└── tool_output/
    ├── 3c9f1a...bb02.txt
    └── 7de441...90f3.txt
```

`.dagi/pdf_cache/` and `.dagi/temp/` are no longer written to by either subsystem. (No
migration needed — `pdf_cache/` was never wired into `ReadTool.run()`, and `.dagi/temp/`'s
existing contents are stale temp files, safe to ignore or manually delete.)

## Behavior Change

Re-running an identical oversized tool call (byte-identical output) within or across sessions
now reuses the same cache file instead of writing a new one each time. The agent-facing
"Full output saved to ..." message and truncation preview are otherwise unchanged.

## Error Handling

| Condition | Behavior |
|---|---|
| `project_root` / subdir creation fails | `get_or_compute` propagates `OSError`; `output_filter.py` catches it and fails open (returns unfiltered result), matching existing behavior. `_pdf_convert.py` lets it propagate — `ReadTool.run()`'s existing `except Exception as e` wrapper turns it into a friendly `"Error: Could not convert ...` message. |
| Cache file exists but is unreadable/corrupt | Not handled specially — `path.read_text()` raises, propagates the same as any other I/O error at that call site. |

## Testing Strategy

- **New:** `tests/test_hash_cache.py` — unit tests for `cache_path()` and `get_or_compute()`:
  cache miss calls `compute()` and writes; cache hit skips `compute()` entirely (assert via a
  call-counting stub); different keys produce different paths; directory auto-created.
- **Updated:** `tests/test_output_filter.py` — replace `tmp_path` (pytest fixture used directly
  as `temp_dir`) with a `project_root` fixture; assertions on the saved-file path now check
  `.dagi/hash_cache/tool_output/<hash>.txt` instead of `tool_output_*.txt`; add a new test
  asserting that filtering the same oversized result twice produces the same cache file (dedup).
- **Updated:** `tests/test_read_tool.py` (wherever `_pdf_convert` is exercised) — cache path
  assertions move from `.dagi/pdf_cache/` to `.dagi/hash_cache/pdf/`.

## Non-goals

- **Cache eviction/cleanup** — deferred, matching the PDF cache design's original precedent.
- **Migrating existing `.dagi/temp/` or `.dagi/pdf_cache/` contents** — not needed; see
  Directory Layout above.
- **Cross-project cache sharing** — each project's `.dagi/hash_cache/` is independent; no global
  cache across projects.
