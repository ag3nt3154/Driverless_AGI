# Document Converter Service Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract document conversion (PDF, docx, xlsx, pptx) from the `read` tool into a standalone FastAPI microservice, and restructure all tools into subfolders.

**Architecture:** Two-phase approach. Phase 1 restructures `tools/` so every tool lives in `tools/{name}/` with `__init__.py` re-exports (zero behavior change, verified by existing test suite). Phase 2 creates the FastAPI service at `services/doc_converter/`, adds an HTTP client module to `tools/read/`, and strips document-conversion dependencies from dagi.

**Tech Stack:** FastAPI, uvicorn, httpx, existing docling/markitdown/pymupdf/ocrmypdf stack (moved to service)

**Spec:** `docs/superpowers/specs/2026-07-25-doc-converter-service-design.md`

---

## Phase 1: Tool Directory Restructure

### Task 1: Restructure simple single-file tools (batch 1)

Move the first batch of simple tools into subfolders. These tools have no cross-tool imports (only import from `agent.base_tool` and shared helpers at `tools/` level).

**Files:**
- Create: `tools/write/__init__.py`, `tools/write/_write.py`
- Create: `tools/edit/__init__.py`, `tools/edit/_edit.py`
- Create: `tools/copy/__init__.py`, `tools/copy/_copy.py`
- Create: `tools/find/__init__.py`, `tools/find/_find.py`
- Create: `tools/grep/__init__.py`, `tools/grep/_grep.py`
- Create: `tools/bash/__init__.py`, `tools/bash/_bash.py`
- Delete: `tools/write.py`, `tools/edit.py`, `tools/copy.py`, `tools/find.py`, `tools/grep.py`, `tools/bash.py`

- [ ] **Step 1: Create `tools/write/` subfolder**

```python
# tools/write/__init__.py
from tools.write._write import WriteTool

__all__ = ["WriteTool"]
```

Move `tools/write.py` → `tools/write/_write.py` with no content changes.

- [ ] **Step 2: Create `tools/edit/` subfolder**

```python
# tools/edit/__init__.py
from tools.edit._edit import EditTool

__all__ = ["EditTool"]
```

Move `tools/edit.py` → `tools/edit/_edit.py` with no content changes.

- [ ] **Step 3: Create `tools/copy/` subfolder**

```python
# tools/copy/__init__.py
from tools.copy._copy import CopyTool

__all__ = ["CopyTool"]
```

Move `tools/copy.py` → `tools/copy/_copy.py` with no content changes.

- [ ] **Step 4: Create `tools/find/` subfolder**

```python
# tools/find/__init__.py
from tools.find._find import FindTool

__all__ = ["FindTool"]
```

Move `tools/find.py` → `tools/find/_find.py` with no content changes.

- [ ] **Step 5: Create `tools/grep/` subfolder**

```python
# tools/grep/__init__.py
from tools.grep._grep import GrepTool

__all__ = ["GrepTool"]
```

Move `tools/grep.py` → `tools/grep/_grep.py` with no content changes.

- [ ] **Step 6: Create `tools/bash/` subfolder**

```python
# tools/bash/__init__.py
from tools.bash._bash import BashTool

__all__ = ["BashTool"]
```

Move `tools/bash.py` → `tools/bash/_bash.py` with no content changes.

- [ ] **Step 7: Delete original flat files**

Delete: `tools/write.py`, `tools/edit.py`, `tools/copy.py`, `tools/find.py`, `tools/grep.py`, `tools/bash.py`

- [ ] **Step 8: Run tests to verify no breakage**

Run: `conda run -n dagi pytest tests/test_scope_tools.py tests/test_bash_tools.py -v`
Expected: All PASS — imports via `from tools.write import WriteTool` etc. resolve through `__init__.py` re-exports.

- [ ] **Step 9: Commit**

```bash
git add tools/write/ tools/edit/ tools/copy/ tools/find/ tools/grep/ tools/bash/
git add -u tools/write.py tools/edit.py tools/copy.py tools/find.py tools/grep.py tools/bash.py
git commit -m "refactor: move write/edit/copy/find/grep/bash tools into subfolders"
```

---

### Task 2: Restructure multi-class tool files (git, plan_mode, schedule_tools)

These files export multiple tool classes from a single file. The `__init__.py` must re-export all of them.

**Files:**
- Create: `tools/git/__init__.py`, `tools/git/_git.py`
- Create: `tools/plan_mode/__init__.py`, `tools/plan_mode/_plan_mode.py`
- Create: `tools/schedule_tools/__init__.py`, `tools/schedule_tools/_schedule_tools.py`
- Delete: `tools/git.py`, `tools/plan_mode.py`, `tools/schedule_tools.py`

- [ ] **Step 1: Create `tools/git/` subfolder**

```python
# tools/git/__init__.py
from tools.git._git import (
    GitAddTool,
    GitBranchTool,
    GitCheckoutTool,
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitResetTool,
    GitStatusTool,
)

__all__ = [
    "GitAddTool",
    "GitBranchTool",
    "GitCheckoutTool",
    "GitCommitTool",
    "GitDiffTool",
    "GitLogTool",
    "GitResetTool",
    "GitStatusTool",
]
```

Move `tools/git.py` → `tools/git/_git.py` with no content changes.

- [ ] **Step 2: Create `tools/plan_mode/` subfolder**

```python
# tools/plan_mode/__init__.py
from tools.plan_mode._plan_mode import (
    EnterPlanModeTool,
    ExitPlanModeTool,
    ENTER_PLAN_MODE_SENTINEL,
    EXIT_PLAN_MODE_SENTINEL,
)

__all__ = [
    "EnterPlanModeTool",
    "ExitPlanModeTool",
    "ENTER_PLAN_MODE_SENTINEL",
    "EXIT_PLAN_MODE_SENTINEL",
]
```

Move `tools/plan_mode.py` → `tools/plan_mode/_plan_mode.py` with no content changes.

Note: `agent/loop.py` imports `ENTER_PLAN_MODE_SENTINEL` and `EXIT_PLAN_MODE_SENTINEL` from `tools.plan_mode` — this works because the `__init__.py` re-exports them.

- [ ] **Step 3: Create `tools/schedule_tools/` subfolder**

```python
# tools/schedule_tools/__init__.py
from tools.schedule_tools._schedule_tools import (
    ListScheduledTasksTool,
    RemoveScheduledTaskTool,
    ScheduleTaskTool,
)

__all__ = [
    "ListScheduledTasksTool",
    "RemoveScheduledTaskTool",
    "ScheduleTaskTool",
]
```

Move `tools/schedule_tools.py` → `tools/schedule_tools/_schedule_tools.py` with no content changes.

- [ ] **Step 4: Delete original flat files**

Delete: `tools/git.py`, `tools/plan_mode.py`, `tools/schedule_tools.py`

- [ ] **Step 5: Run tests**

Run: `conda run -n dagi pytest tests/test_git_tools.py tests/test_scheduler.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/git/ tools/plan_mode/ tools/schedule_tools/
git add -u tools/git.py tools/plan_mode.py tools/schedule_tools.py
git commit -m "refactor: move git/plan_mode/schedule_tools into subfolders"
```

---

### Task 3: Restructure remaining simple tools (batch 2)

The remaining single-class tools with no tricky imports.

**Files:**
- Create subfolders for: `skill`, `web_search`, `web_fetch`, `compact`, `switch_model`, `workflow`, `reload_skills`, `emote`, `ask_user`, `show_plan`, `complete_plan`, `explore_files`, `web_research`, `run_skill_script`, `escalate_issue`, `spawn_subagent`, `cli_subagent`, `extend_timeout`
- Delete: corresponding flat `.py` files

- [ ] **Step 1: Create subfolders for tools that export sentinels or constants**

These tools have module-level constants imported by `agent/loop.py` or other tools — the `__init__.py` must re-export them.

`tools/compact/`:
```python
# tools/compact/__init__.py
from tools.compact._compact import CompactTool, CompactionResult, _NO_COMPACTION

__all__ = ["CompactTool", "CompactionResult", "_NO_COMPACTION"]
```

`tools/complete_plan/`:
```python
# tools/complete_plan/__init__.py
from tools.complete_plan._complete_plan import CompletePlanTool, COMPLETE_PLAN_SENTINEL

__all__ = ["CompletePlanTool", "COMPLETE_PLAN_SENTINEL"]
```

`tools/reload_skills/`:
```python
# tools/reload_skills/__init__.py
from tools.reload_skills._reload_skills import ReloadSkillsTool, RELOAD_SKILLS_SENTINEL

__all__ = ["ReloadSkillsTool", "RELOAD_SKILLS_SENTINEL"]
```

`tools/switch_model/`:
```python
# tools/switch_model/__init__.py
from tools.switch_model._switch_model import SwitchModelTool, parse_switch_sentinel

__all__ = ["SwitchModelTool", "parse_switch_sentinel"]
```

`tools/spawn_subagent/`:
```python
# tools/spawn_subagent/__init__.py
from tools.spawn_subagent._spawn_subagent import SpawnSubagentTool, _FALLBACK_PARAMETERS

__all__ = ["SpawnSubagentTool", "_FALLBACK_PARAMETERS"]
```

Move each corresponding `.py` → `_{name}.py`, delete originals.

- [ ] **Step 2: Create subfolders for remaining simple tools**

These have no constants imported externally — `__init__.py` just re-exports the tool class.

Pattern for each (replace `{Name}` and `{name}`):
```python
# tools/{name}/__init__.py
from tools.{name}._{name} import {Name}Tool

__all__ = ["{Name}Tool"]
```

Apply to: `skill` (`SkillTool`), `web_search` (`WebSearchTool`), `web_fetch` (`WebFetchTool`), `workflow` (`WorkflowTool`), `emote` (`EmoteTool`), `ask_user` (`AskUserTool`), `show_plan` (`ShowPlanTool`), `explore_files` (`ExploreFilesTool`), `web_research` (`WebResearchTool`), `run_skill_script` (`RunSkillScriptTool`), `escalate_issue` (`EscalateIssueTool`), `cli_subagent` (`SpawnCliSubagentTool`), `extend_timeout` (`ExtendSubagentTimeoutTool`)

Move each `.py` → `_{name}.py`, delete originals.

- [ ] **Step 3: Fix cross-tool lazy imports inside moved files**

After the restructure, these lazy imports inside tool files still work because they reference the package path (resolved via `__init__.py`):

- `tools/extend_timeout/_extend_timeout.py` line 36: `from tools.spawn_subagent import SpawnSubagentTool` ✓ (resolves via `__init__.py`)
- `tools/extend_timeout/_extend_timeout.py` line 35: `from tools._subagent_runner import resume_subagent` ✓ (`_subagent_runner` stays at `tools/` level)
- `tools/spawn_subagent/_spawn_subagent.py` line 55,85: `from tools._plan_parser import extract_subtask` ✓ (`_plan_parser` stays at `tools/` level)

No changes needed — verify by reading the moved files.

- [ ] **Step 4: Run full test suite**

Run: `conda run -n dagi pytest tests/ -v --timeout=60`
Expected: All existing tests PASS. This is the critical gate — if anything fails, an `__init__.py` re-export is missing.

- [ ] **Step 5: Commit**

```bash
git add tools/skill/ tools/web_search/ tools/web_fetch/ tools/compact/ tools/switch_model/ tools/workflow/ tools/reload_skills/ tools/emote/ tools/ask_user/ tools/show_plan/ tools/complete_plan/ tools/explore_files/ tools/web_research/ tools/run_skill_script/ tools/escalate_issue/ tools/spawn_subagent/ tools/cli_subagent/ tools/extend_timeout/
git add -u tools/skill.py tools/web_search.py tools/web_fetch.py tools/compact.py tools/switch_model.py tools/workflow.py tools/reload_skills.py tools/emote.py tools/ask_user.py tools/show_plan.py tools/complete_plan.py tools/explore_files.py tools/web_research.py tools/run_skill_script.py tools/escalate_issue.py tools/spawn_subagent.py tools/cli_subagent.py tools/extend_timeout.py
git commit -m "refactor: move remaining 18 tools into subfolders"
```

---

### Task 4: Restructure `read` tool and relocate `_document_reader.py`

The `read` tool is the most complex — it has private helpers that move into its subfolder.

**Files:**
- Create: `tools/read/__init__.py`, `tools/read/_read.py`
- Move: `tools/_document_reader.py` → `tools/read/_document_reader.py`
- Delete: `tools/read.py`, `tools/_document_reader.py`
- Modify: `tools/read/_read.py` (update import path for `_document_reader`)
- Modify: `tests/test_read_tool.py` (update patch target for `summarize_document`)
- Modify: `tests/test_document_reader.py` (update import path)

- [ ] **Step 1: Create `tools/read/` subfolder**

```python
# tools/read/__init__.py
from tools.read._read import ReadTool

__all__ = ["ReadTool"]
```

Move `tools/read.py` → `tools/read/_read.py`.

- [ ] **Step 2: Move `_document_reader.py` into `tools/read/`**

Move `tools/_document_reader.py` → `tools/read/_document_reader.py`.

No content changes needed — `_document_reader.py` imports `from tools._subagent_runner import run_subagent`, which still resolves because `_subagent_runner.py` stays at `tools/` level.

- [ ] **Step 3: Update import in `_read.py`**

In `tools/read/_read.py`, change line 9:

```python
# OLD
    from tools._document_reader import summarize_document
# NEW
    from tools.read._document_reader import summarize_document
```

- [ ] **Step 4: Update test patch targets**

In `tests/test_read_tool.py`, the `TestAutoSummarization` class patches `"tools.read.summarize_document"`. After restructure, `summarize_document` lives in `tools/read/_read.py` (where it's imported), so the patch target becomes `"tools.read._read.summarize_document"`:

```python
# tests/test_read_tool.py — TestAutoSummarization

# OLD (3 occurrences)
        with patch("tools.read.summarize_document", ...):

# NEW (3 occurrences)
        with patch("tools.read._read.summarize_document", ...):
```

In `tests/test_document_reader.py`, line 5:

```python
# OLD
from tools._document_reader import summarize_document
# NEW
from tools.read._document_reader import summarize_document
```

- [ ] **Step 5: Delete original files**

Delete: `tools/read.py`, `tools/_document_reader.py`

- [ ] **Step 6: Run tests**

Run: `conda run -n dagi pytest tests/test_read_tool.py tests/test_document_reader.py tests/test_scope_tools.py -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/read/
git add -u tools/read.py tools/_document_reader.py
git add tests/test_read_tool.py tests/test_document_reader.py
git commit -m "refactor: move read tool + document_reader into tools/read/ subfolder"
```

---

### Task 5: Full test suite verification + cleanup

- [ ] **Step 1: Run the complete test suite**

Run: `conda run -n dagi pytest tests/ -v --timeout=60`
Expected: All tests PASS. Every import path resolves through `__init__.py` re-exports.

- [ ] **Step 2: Verify no stale `.py` files remain at `tools/` level (except shared helpers)**

Run: `ls tools/*.py`
Expected remaining files:
```
tools/__init__.py
tools/_path_guard.py
tools/_hash_cache.py
tools/_subagent_runner.py
tools/_plan_parser.py
tools/_pdf_convert.py      (will be deleted in Phase 2)
tools/output_filter.py
tools/subagent_main.py
```

Every other `.py` file should be gone (moved into subfolders).

- [ ] **Step 3: Commit if any cleanup was needed**

```bash
git commit -m "refactor: phase 1 complete — all tools in subfolders"
```

---

## Phase 2: Document Converter Service

### Task 6: Create FastAPI service skeleton

**Files:**
- Create: `services/doc_converter/__init__.py`
- Create: `services/doc_converter/__main__.py`
- Create: `services/doc_converter/main.py`
- Create: `services/doc_converter/converter/__init__.py`
- Create: `services/doc_converter/converter/cache.py`
- Create: `services/doc_converter/environment.yml`

- [ ] **Step 1: Create `services/` directory and service package**

```bash
mkdir -p services/doc_converter/converter
```

- [ ] **Step 2: Create `environment.yml`**

```yaml
# services/doc_converter/environment.yml
name: doc_converter
channels:
  - defaults
  - conda-forge
dependencies:
  - python=3.14
  - pip
  - pip:
    - fastapi>=0.115
    - uvicorn[standard]>=0.30
    - python-multipart>=0.0.9
    - docling>=2.75
    - pymupdf>=1.26.6
    - ocrmypdf>=16.0
    - markitdown>=0.1.0
    - torch
    - psutil>=5.9.0
```

- [ ] **Step 3: Create the server-side cache module**

```python
# services/doc_converter/converter/cache.py
"""Content-addressed cache for converted documents."""
from __future__ import annotations

import hashlib
from pathlib import Path

_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def cache_dir() -> Path:
    """Return (and create) the server-side cache directory."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def hash_bytes(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def get_cached(content_hash: str) -> str | None:
    """Return cached markdown if it exists, else None."""
    path = cache_dir() / f"{content_hash}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def store(content_hash: str, markdown: str) -> Path:
    """Write markdown to cache and return the cache file path."""
    path = cache_dir() / f"{content_hash}.md"
    path.write_text(markdown, encoding="utf-8", newline="\n")
    return path
```

- [ ] **Step 4: Create `converter/__init__.py` with the conversion dispatch**

```python
# services/doc_converter/converter/__init__.py
"""Document conversion dispatch — auto-detects format from filename."""
from __future__ import annotations

from pathlib import Path

_DOC_EXTS = {".docx", ".xlsx", ".pptx"}
_PDF_EXT = ".pdf"
_SUPPORTED = _DOC_EXTS | {_PDF_EXT}


def convert(path: Path) -> str:
    """Convert a document file to markdown text.

    Raises:
        ValueError: unsupported format
        RuntimeError: conversion failure
    """
    ext = path.suffix.lower()
    if ext not in _SUPPORTED:
        raise ValueError(f"Unsupported file format: {ext}")

    if ext == _PDF_EXT:
        from services.doc_converter.converter.pdf import convert_pdf
        return convert_pdf(path)

    from services.doc_converter.converter.office import convert_office
    return convert_office(path)
```

- [ ] **Step 5: Create the FastAPI app**

```python
# services/doc_converter/main.py
"""FastAPI document converter service."""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import PlainTextResponse, JSONResponse

from services.doc_converter.converter import convert, _SUPPORTED
from services.doc_converter.converter.cache import hash_bytes, get_cached, store

app = FastAPI(title="DAGI Document Converter")


@app.post("/convert")
async def convert_document(file: UploadFile = File(...)) -> PlainTextResponse:
    """Convert an uploaded document to markdown text."""
    content = await file.read()

    if len(content) == 0:
        return JSONResponse(
            status_code=400,
            content={"error": "Uploaded file is empty.", "code": "FILE_EMPTY"},
        )

    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()
    if ext not in _SUPPORTED:
        return JSONResponse(
            status_code=422,
            content={
                "error": f"Unsupported file format: {ext}",
                "code": "UNSUPPORTED_FORMAT",
            },
        )

    content_hash = hash_bytes(content)
    cached = get_cached(content_hash)
    if cached is not None:
        return PlainTextResponse(cached, media_type="text/markdown")

    # Write to temp file for conversion
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(
        suffix=suffix, delete=False, dir=tempfile.gettempdir()
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        markdown = convert(tmp_path)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": str(exc), "code": "UNSUPPORTED_FORMAT"},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "code": "CONVERSION_FAILED"},
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    store(content_hash, markdown)
    return PlainTextResponse(markdown, media_type="text/markdown")
```

- [ ] **Step 6: Create `__main__.py` for `python -m services.doc_converter`**

```python
# services/doc_converter/__main__.py
"""Entry point: python -m services.doc_converter"""
import uvicorn


def main() -> None:
    uvicorn.run(
        "services.doc_converter.main:app",
        host="0.0.0.0",
        port=8100,
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

```python
# services/doc_converter/__init__.py
```

- [ ] **Step 7: Commit**

```bash
git add services/
git commit -m "feat: create doc_converter FastAPI service skeleton with cache"
```

---

### Task 7: Move PDF conversion logic to service

Move `tools/_pdf_convert.py` into the service, adapting imports.

**Files:**
- Create: `services/doc_converter/converter/pdf.py`
- Create: `services/doc_converter/converter/office.py`

- [ ] **Step 1: Create `converter/office.py`**

```python
# services/doc_converter/converter/office.py
"""Convert docx/xlsx/pptx files to markdown via markitdown."""
from __future__ import annotations

from pathlib import Path


def convert_office(path: Path) -> str:
    """Convert a docx/xlsx/pptx file to markdown text."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        raise RuntimeError(
            "markitdown is not installed in the doc_converter environment."
        )
    result = MarkItDown().convert(str(path))
    return result.text_content
```

- [ ] **Step 2: Create `converter/pdf.py` from `tools/_pdf_convert.py`**

Copy `tools/_pdf_convert.py` → `services/doc_converter/converter/pdf.py`.

Apply these changes:
1. Remove the import of `from agent import DAGI_ROOT` — the service doesn't use DAGI_ROOT.
2. Remove the import of `from agent.config_loader import load_pdf_config` — the service manages its own config.
3. Remove the import of `from tools._hash_cache import cache_path, get_or_compute` — the service uses its own `converter.cache` module.
4. Remove `_DOCLING_ARTIFACTS_PATH` (referenced DAGI_ROOT).
5. Change the `convert_pdf` function signature: instead of `(pdf_path, cwd)` returning `(str, Path)`, make it `(pdf_path: Path) -> str` — the service manages its own cache externally (in `main.py`).
6. The internal functions (`_convert_pdf_digital`, `_convert_pdf_scanned`, `is_scanned_pdf`, `_estimate_worker_count`, `_split_into_chunks`, `_convert_chunk`, `_convert_pdf_parallel`, `_renumber_markers`, `parse_page_spec`, `select_pages`, `_get_page_count`) can be moved largely as-is.
7. For `_estimate_worker_count`: replace `load_pdf_config()` call with reading from environment variables or service-level config (e.g. `os.environ.get("PDF_WORKER_RAM_GB", "4.0")`).

The key function to adapt:

```python
def convert_pdf(pdf_path: Path) -> str:
    """Convert a PDF to markdown text. Returns the markdown string.

    The server-side cache is handled by the caller (main.py).
    This function always performs the conversion.
    """
    is_scanned = is_scanned_pdf(pdf_path)
    page_count = _get_page_count(pdf_path)

    if page_count > PDF_PARALLEL_MIN_PAGES:
        worker_count = _estimate_worker_count(page_count)
        if worker_count > 1:
            cache_dir = Path(tempfile.mkdtemp(prefix="dagi_pdf_"))
            try:
                return _convert_pdf_parallel(
                    pdf_path, cache_dir, is_scanned,
                    page_count=page_count, worker_count=worker_count,
                )
            finally:
                import shutil
                shutil.rmtree(cache_dir, ignore_errors=True)

    if is_scanned:
        return _convert_pdf_scanned(pdf_path)
    return _convert_pdf_digital(pdf_path)
```

- [ ] **Step 3: Verify service starts**

Run: `conda run -n doc_converter python -m services.doc_converter`
Expected: Uvicorn starts on port 8100, `INFO: Application startup complete.`
(Kill with Ctrl+C after verifying.)

Note: The `doc_converter` conda env must be created first from `environment.yml`:
```bash
conda env create -f services/doc_converter/environment.yml
```

- [ ] **Step 4: Commit**

```bash
git add services/doc_converter/converter/
git commit -m "feat: move PDF + office conversion logic into service"
```

---

### Task 8: Create the DAGI-side HTTP client module

**Files:**
- Create: `tools/read/_doc_service.py`

- [ ] **Step 1: Create `_doc_service.py`**

```python
# tools/read/_doc_service.py
"""HTTP client for the document converter service.

Anti-corruption layer: all HTTP details (endpoint, auth, headers, error
mapping) are encapsulated here. When the service API evolves, only this
file changes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from tools._hash_cache import get_or_compute

_DOC_CACHE_SUBDIR = "doc_convert"
_TIMEOUT = 300.0  # 5 minutes — large PDFs with OCR can be slow


class DocServiceError(Exception):
    """Raised when the document converter service returns an error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def convert_document(
    path: Path,
    service_url: str,
    project_path: Path,
) -> str:
    """Convert a document file to markdown via the converter service.

    Checks the local hash cache first. On miss, uploads to the service
    and caches the result locally.

    Args:
        path: Absolute path to the document file.
        service_url: Base URL of the converter service (e.g. http://localhost:8100).
        project_path: Project root — local cache lives under .dagi/hash_cache/.

    Returns:
        Markdown text of the converted document.

    Raises:
        DocServiceError: on service errors (with code and message).
    """
    file_bytes = path.read_bytes()
    content_hash = hashlib.sha256(file_bytes).hexdigest()

    # Local cache check
    cache_dir = project_path / ".dagi" / "hash_cache" / _DOC_CACHE_SUBDIR
    cache_file = cache_dir / f"{content_hash}.md"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    # Cache miss — call service
    url = f"{service_url.rstrip('/')}/convert"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.post(
                url,
                files={"file": (path.name, file_bytes)},
            )
    except httpx.ConnectError:
        raise DocServiceError(
            "CONNECTION_FAILED",
            f"Document conversion service is not running at {service_url}. "
            f"Start it with: python -m services.doc_converter",
        )
    except httpx.TimeoutException:
        raise DocServiceError(
            "TIMEOUT",
            f"Document conversion service timed out after {_TIMEOUT}s. "
            f"The document may be too large or the service may be overloaded.",
        )

    if response.status_code == 200:
        markdown = response.text
        # Store in local cache
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(markdown, encoding="utf-8", newline="\n")
        return markdown

    # Error response — parse JSON error detail
    try:
        error_body = response.json()
        code = error_body.get("code", "UNKNOWN")
        message = error_body.get("error", response.text)
    except Exception:
        code = f"HTTP_{response.status_code}"
        message = response.text

    raise DocServiceError(code, message)
```

- [ ] **Step 2: Commit**

```bash
git add tools/read/_doc_service.py
git commit -m "feat: add doc service HTTP client module"
```

---

### Task 9: Simplify `read` tool to delegate document conversion

**Files:**
- Modify: `tools/read/_read.py`
- Modify: `tests/test_read_tool.py`

- [ ] **Step 1: Rewrite `tools/read/_read.py`**

Replace the current `_read.py` content with the simplified version. Key changes:
- Remove `from tools._pdf_convert import convert_pdf, select_pages`
- Remove `_convert_document()`, `_MARKITDOWN_EXTS`
- Add `from tools.read._doc_service import convert_document, DocServiceError`
- Add page-selection logic inline (move `select_pages` and `parse_page_spec` into `_read.py` since they're simple text operations — or import from `_doc_service` if preferred)
- Route document extensions through `convert_document()`

```python
# tools/read/_read.py
"""Read tool — text files inline, documents via converter service."""
import re
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path
from tools.read._doc_service import convert_document, DocServiceError

try:
    from tools.read._document_reader import summarize_document
except ImportError:
    summarize_document = None  # type: ignore[assignment]

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_BLOCKED_EXTS = _IMAGE_EXTS.copy()
_DOC_EXTS = {".pdf", ".docx", ".xlsx", ".pptx"}
_PAGE_MARKER_RE = re.compile(r"<!-- Page (\d+) -->")


def _parse_page_spec(spec: str) -> set[int]:
    """Parse a page spec like '1-3,5,8-10' into a set of page numbers."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                start, end = int(bounds[0].strip()), int(bounds[1].strip())
            except ValueError:
                raise ValueError(f"Invalid page spec: {spec!r}")
            pages.update(range(start, end + 1))
        else:
            try:
                pages.add(int(part))
            except ValueError:
                raise ValueError(f"Invalid page spec: {spec!r}")
    return pages


def _select_pages(md_text: str, page_spec: str) -> str:
    """Filter markdown to only include the specified pages."""
    wanted = _parse_page_spec(page_spec)
    sections = _PAGE_MARKER_RE.split(md_text)
    result_parts: list[str] = []
    # sections[0] is text before first marker (if any)
    i = 1
    while i < len(sections):
        page_num = int(sections[i])
        content = sections[i + 1] if i + 1 < len(sections) else ""
        if page_num in wanted:
            result_parts.append(f"<!-- Page {page_num} -->{content}")
        i += 2
    return "".join(result_parts)


class ReadTool(BaseTool):
    name = "read"
    description = (
        "Read the contents of a file. Supports all text files (any extension) — "
        "attempts UTF-8 decoding. Defaults to first 2000 lines. "
        ".docx, .xlsx, .pptx, and .pdf files are converted to markdown via the "
        "document converter service (must be running). "
        "Use the optional `pages` parameter to select specific PDF pages. "
        "Use offset/limit for large files. Accepts both relative paths "
        "(resolved from the project root) and absolute paths. "
        "Output uses `cat -n` style: each line is prefixed with its 1-indexed "
        "line number followed by a tab — the number is not part of the file content. "
        "For large-scale codebase exploration, prefer `explore_files`."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read (relative to project root, or absolute)",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
            },
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

    def __init__(
        self,
        cwd: Path = Path("."),
        allowed_roots: list[Path] | None = None,
        reserve_tokens: int = 0,
        project_path: Path | None = None,
        service_url: str | None = None,
    ):
        self.cwd = cwd
        self.allowed_roots = allowed_roots
        self._reserve_tokens = reserve_tokens
        self._project_path = project_path
        self._service_url = service_url

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

        if ext in _BLOCKED_EXTS:
            return (
                f"Error: Cannot read file type '{ext}'. This file type is not "
                f"currently supported by the read tool."
            )

        header = None

        if ext in _DOC_EXTS:
            if not self._service_url or not self._project_path:
                return (
                    "Error: Document reading requires the converter service. "
                    "Ensure services.doc_converter is configured in config.yaml."
                )
            try:
                md_text = convert_document(p, self._service_url, self._project_path)
            except DocServiceError as exc:
                return f"Error from document service ({exc.code}): {exc.message}"

            if ext == ".pdf":
                total_pages = md_text.count("<!-- Page ")
                if pages:
                    md_text = _select_pages(md_text, pages)
                header = f"[PDF: {p.name} | {total_pages} pages"
                if pages:
                    header += f" | showing pages {pages}"
                header += "]"

            lines = md_text.splitlines()

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

        raw_result = f"{header}\n{numbered}" if header else numbered

        # Auto-summarization gate
        if (
            self._reserve_tokens > 0
            and self._project_path is not None
            and summarize_document is not None
            and offset == 1
            and limit == 2000
        ):
            _CHARS_PER_TOKEN = 4
            full_text = "\n".join(
                f"{i:6d}\t{line}" for i, line in enumerate(lines, 1)
            )
            estimated_tokens = len(full_text) // _CHARS_PER_TOKEN
            if estimated_tokens >= self._reserve_tokens:
                summary = summarize_document(
                    full_text=full_text,
                    source_path=p,
                    filename=p.name,
                    project_path=self._project_path,
                )
                if summary is not None:
                    return summary

        return raw_result
```

- [ ] **Step 2: Update `ReadTool` registration in `agent/tools.py`**

In `agent/tools.py`, update the `ReadTool` constructor call to pass `service_url`:

```python
# agent/tools.py — in create_tool_registry(), around line 261

# OLD
    reg.register(ReadTool(
        cwd=cwd,
        allowed_roots=effective_roots,
        reserve_tokens=_reserve,
        project_path=_proj,
    ))

# NEW
    _services = config.services if config else {}
    reg.register(ReadTool(
        cwd=cwd,
        allowed_roots=effective_roots,
        reserve_tokens=_reserve,
        project_path=_proj,
        service_url=_services.get("doc_converter"),
    ))
```

- [ ] **Step 3: Add `services` loading to `agent/config_loader.py`**

Add to `_build_config_from_entry()` — load the `services` dict from raw config. Since `AgentConfig` is a dataclass in `agent/loop.py`, add a `services` field there:

In `agent/loop.py`, add to `AgentConfig`:
```python
    services: dict[str, str] = field(default_factory=dict)
```

In `agent/config_loader.py`, in `_build_config_from_entry()`:
```python
    services = raw.get("services") or {}
```

And pass it to the `AgentConfig` constructor:
```python
    return AgentConfig(
        ...
        services=services,
    )
```

- [ ] **Step 4: Remove `PdfConfig` and `load_pdf_config` from `agent/config_loader.py`**

Delete lines 69-83 (the `PdfConfig` dataclass and `load_pdf_config` function). They are no longer referenced by anything in dagi.

- [ ] **Step 5: Commit**

```bash
git add tools/read/_read.py agent/tools.py agent/config_loader.py agent/loop.py
git commit -m "feat: read tool delegates document conversion to service"
```

---

### Task 10: Rewrite tests for new read tool behavior

**Files:**
- Modify: `tests/test_read_tool.py`
- Create: `tests/test_doc_service.py`

- [ ] **Step 1: Remove all document-conversion test classes from `test_read_tool.py`**

Delete these entire classes/sections (they tested inline conversion that no longer exists in dagi):
- `TestDocumentFormatConversion` (lines 37-108)
- `_install_fake_fitz` and all PDF fake helpers (lines 110-302)
- `TestParsePageSpec` (lines 156-174)
- `TestSelectPages` (lines 177-201)
- `_install_fake_docling`, `_install_fake_ocrmypdf`, `_install_all_pdf_fakes` (lines 203-301)
- `TestIsScannedPdf` (lines 307-334)
- `TestGetPageCount` (lines 340-353)
- `_install_fake_psutil` (lines 356-364)
- `TestEstimateWorkerCount` (lines 370-430)
- `TestRenumberMarkers` (lines 436-459)
- `TestSplitIntoChunks` (lines 465-516)
- `TestConvertChunk` (lines 522-575)
- `TestConvertPdf` (lines 643-849)
- `TestConvertPdfParallel` (lines 586-638)
- `TestReadToolPdf` (lines 852-930)

Also delete the imports at lines 153, 304, 337, 367, 433, 462, 519, 578, 581, 583:
```python
from tools._pdf_convert import ...
```

And delete `_install_fake_markitdown` (lines 14-30) — no longer needed.

- [ ] **Step 2: Keep and update remaining test classes**

Keep `TestAutoSummarization` (lines 934-993) — update patch targets:

```python
# OLD
        with patch("tools.read.summarize_document", ...):
# NEW
        with patch("tools.read._read.summarize_document", ...):
```

Add new tests for document routing through the service:

```python
from unittest.mock import patch, MagicMock
from tools.read._doc_service import DocServiceError


def _make_tool(tmp_path, service_url="http://localhost:8100"):
    return ReadTool(
        cwd=tmp_path,
        allowed_roots=[tmp_path],
        service_url=service_url,
        project_path=tmp_path,
    )


class TestTextFileReading:
    """Text file reading — unchanged behavior."""

    def test_reads_text_file(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello\nworld", encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt")

        assert result == _numbered(["hello", "world"])

    def test_offset_and_limit(self, tmp_path):
        text = "\n".join(f"line{i}" for i in range(1, 11))
        f = tmp_path / "notes.txt"
        f.write_text(text, encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt", offset=3, limit=2)

        assert result == _numbered(["line3", "line4"], start=3)

    def test_binary_file_returns_error(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02\xff\xfe")
        tool = _make_tool(tmp_path)

        result = tool.run(path="data.bin")

        assert "binary" in result.lower() or "UTF-8" in result

    def test_blocked_extension_returns_error(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake jpg")
        tool = _make_tool(tmp_path)

        result = tool.run(path="photo.jpg")

        assert result.startswith("Error:")

    def test_pages_on_non_pdf_returns_error(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello", encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt", pages="1-3")

        assert "only supported for PDF" in result


class TestDocumentRouting:
    """Document files are routed through the service client."""

    @patch("tools.read._read.convert_document")
    def test_docx_routed_to_service(self, mock_convert, tmp_path):
        mock_convert.return_value = "# Heading\n\nParagraph."
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake docx")
        tool = _make_tool(tmp_path)

        result = tool.run(path="doc.docx")

        mock_convert.assert_called_once()
        assert "# Heading" in result

    @patch("tools.read._read.convert_document")
    def test_pdf_routed_to_service_with_page_header(self, mock_convert, tmp_path):
        mock_convert.return_value = (
            "<!-- Page 1 -->\n# Title\n\n"
            "<!-- Page 2 -->\n## Chapter 1\n"
        )
        f = tmp_path / "report.pdf"
        f.write_bytes(b"fake pdf")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf")

        assert result.startswith("[PDF: report.pdf |")
        assert "# Title" in result

    @patch("tools.read._read.convert_document")
    def test_pdf_pages_parameter_filters(self, mock_convert, tmp_path):
        mock_convert.return_value = (
            "<!-- Page 1 -->\n# Title\n\n"
            "<!-- Page 2 -->\n## Chapter 1\n"
            "<!-- Page 3 -->\n## Chapter 2\n"
        )
        f = tmp_path / "report.pdf"
        f.write_bytes(b"fake pdf")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf", pages="2")

        assert "## Chapter 1" in result
        assert "# Title" not in result

    @patch("tools.read._read.convert_document")
    def test_service_error_returned_to_llm(self, mock_convert, tmp_path):
        mock_convert.side_effect = DocServiceError(
            "CONVERSION_FAILED", "docling crashed on page 3"
        )
        f = tmp_path / "report.pdf"
        f.write_bytes(b"fake pdf")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf")

        assert "CONVERSION_FAILED" in result
        assert "docling crashed on page 3" in result

    def test_no_service_url_returns_config_error(self, tmp_path):
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake docx")
        tool = ReadTool(
            cwd=tmp_path, allowed_roots=[tmp_path],
            service_url=None, project_path=tmp_path,
        )

        result = tool.run(path="doc.docx")

        assert "converter service" in result.lower()
```

- [ ] **Step 3: Create `tests/test_doc_service.py`**

```python
# tests/test_doc_service.py
"""Tests for the document service HTTP client (tools/read/_doc_service.py)."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tools.read._doc_service import convert_document, DocServiceError


class TestLocalCacheHit:
    def test_returns_cached_markdown_without_http(self, tmp_path):
        # Pre-populate cache
        import hashlib
        content = b"fake pdf bytes"
        content_hash = hashlib.sha256(content).hexdigest()
        cache_dir = tmp_path / ".dagi" / "hash_cache" / "doc_convert"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / f"{content_hash}.md"
        cache_file.write_text("# Cached Result", encoding="utf-8")

        doc = tmp_path / "report.pdf"
        doc.write_bytes(content)

        result = convert_document(doc, "http://localhost:8100", tmp_path)

        assert result == "# Cached Result"


class TestCacheMiss:
    @patch("tools.read._doc_service.httpx.Client")
    def test_uploads_file_and_caches_response(self, MockClient, tmp_path):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "# Converted\n\nContent."
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        MockClient.return_value = mock_client_instance

        doc = tmp_path / "doc.docx"
        doc.write_bytes(b"fake docx bytes")

        result = convert_document(doc, "http://localhost:8100", tmp_path)

        assert result == "# Converted\n\nContent."
        mock_client_instance.post.assert_called_once()

        # Verify cached
        import hashlib
        h = hashlib.sha256(b"fake docx bytes").hexdigest()
        cache_file = tmp_path / ".dagi" / "hash_cache" / "doc_convert" / f"{h}.md"
        assert cache_file.exists()
        assert cache_file.read_text(encoding="utf-8") == "# Converted\n\nContent."


class TestServiceErrors:
    @patch("tools.read._doc_service.httpx.Client")
    def test_connection_refused_raises_doc_service_error(self, MockClient, tmp_path):
        import httpx
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.side_effect = httpx.ConnectError("refused")
        MockClient.return_value = mock_client_instance

        doc = tmp_path / "doc.pdf"
        doc.write_bytes(b"fake pdf")

        with pytest.raises(DocServiceError, match="CONNECTION_FAILED"):
            convert_document(doc, "http://localhost:8100", tmp_path)

    @patch("tools.read._doc_service.httpx.Client")
    def test_server_error_passes_through_code_and_message(self, MockClient, tmp_path):
        import json
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {
            "error": "docling crashed", "code": "CONVERSION_FAILED"
        }
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        MockClient.return_value = mock_client_instance

        doc = tmp_path / "doc.pdf"
        doc.write_bytes(b"fake pdf")

        with pytest.raises(DocServiceError) as exc_info:
            convert_document(doc, "http://localhost:8100", tmp_path)

        assert exc_info.value.code == "CONVERSION_FAILED"
        assert "docling crashed" in exc_info.value.message
```

- [ ] **Step 4: Run tests**

Run: `conda run -n dagi pytest tests/test_read_tool.py tests/test_doc_service.py tests/test_document_reader.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_read_tool.py tests/test_doc_service.py
git commit -m "test: rewrite read tool tests for service-based document conversion"
```

---

### Task 11: Clean up dependencies and delete dead code

**Files:**
- Delete: `tools/_pdf_convert.py`
- Modify: `pyproject.toml`
- Modify: `config.yaml` (add `services:` block)

- [ ] **Step 1: Delete `tools/_pdf_convert.py`**

This file has been moved to `services/doc_converter/converter/pdf.py`. Delete it.

- [ ] **Step 2: Update `pyproject.toml`**

Remove `pdf` and `docs` optional dependency groups. Remove `psutil` from core deps (only consumer was `_pdf_convert.py`; `conftest.py` also uses it — check if conftest needs it as a dev dep):

```toml
# REMOVE these lines:
    "psutil>=5.9.0",       # RAM/CPU introspection — PDF parallel-conversion worker sizing

# REMOVE these entire groups:
# Install to enable DOCX, XLSX, and PPTX reading in the `read` tool.
docs = ["markitdown>=0.1.0"]
# Install to enable PDF reading in the `read` tool.
pdf = [
    "docling>=2.75",
    "pymupdf>=1.26.6",
    "ocrmypdf>=16.0",
]
```

`psutil` is used by `tests/conftest.py` (RAM watchdog). Add it back as a test dependency or keep in core. Since it's lightweight (unlike torch/docling), keeping it in core is fine. Leave it.

Actually, re-checking: `psutil` is only 2MB and `conftest.py` uses it in every test run. Keep it in core deps.

- [ ] **Step 3: Add `services:` block to `config.yaml`**

```yaml
# Document converter service URL (start with: python -m services.doc_converter)
services:
  doc_converter: "http://localhost:8100"
```

- [ ] **Step 4: Run full test suite**

Run: `conda run -n dagi pytest tests/ -v --timeout=60`
Expected: All PASS. No imports reference `tools._pdf_convert` anymore.

- [ ] **Step 5: Commit**

```bash
git add -u tools/_pdf_convert.py
git add pyproject.toml config.yaml
git commit -m "cleanup: remove pdf/docs deps from dagi, add services config"
```

---

### Task 12: Final verification + AGENTS.md update

- [ ] **Step 1: Verify directory structure**

Run: `ls tools/`
Expected: Only subfolders + shared helpers:
```
tools/__init__.py
tools/_path_guard.py
tools/_hash_cache.py
tools/_subagent_runner.py
tools/_plan_parser.py
tools/output_filter.py
tools/subagent_main.py
tools/read/
tools/write/
tools/edit/
tools/bash/
tools/grep/
tools/find/
tools/copy/
tools/git/
tools/plan_mode/
tools/schedule_tools/
tools/skill/
tools/web_search/
tools/web_fetch/
tools/compact/
tools/switch_model/
tools/workflow/
tools/reload_skills/
tools/emote/
tools/ask_user/
tools/show_plan/
tools/complete_plan/
tools/explore_files/
tools/web_research/
tools/run_skill_script/
tools/escalate_issue/
tools/spawn_subagent/
tools/cli_subagent/
tools/extend_timeout/
```

- [ ] **Step 2: Verify service directory structure**

Run: `ls services/doc_converter/`
Expected:
```
services/doc_converter/__init__.py
services/doc_converter/__main__.py
services/doc_converter/main.py
services/doc_converter/environment.yml
services/doc_converter/converter/
```

- [ ] **Step 3: Run full test suite one final time**

Run: `conda run -n dagi pytest tests/ -v --timeout=60`
Expected: All PASS.

- [ ] **Step 4: Update AGENTS.md**

Use skill `update-project-context` to update AGENTS.md with:
- Architecture change: tools in subfolders, document service extracted
- Key files update: `services/doc_converter/`, `tools/read/_doc_service.py`
- Remove notes about `_pdf_convert.py`, `PdfConfig`, `pdf:` config block
- Add notes about `services:` config block, two-layer cache

- [ ] **Step 5: Update README.md and TODO.md**

Per CLAUDE.local.md: ensure README and TODO reflect the new service requirement for document reading.

- [ ] **Step 6: Final commit**

```bash
git add AGENTS.md README.md TODO.md
git commit -m "docs: update project docs for tool restructure + doc converter service"
```
