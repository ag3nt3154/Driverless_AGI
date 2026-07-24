# Document Converter Service Extraction — Design Spec

**Date:** 2026-07-25
**Status:** Approved

---

## Problem

DAGI's `read` tool handles text files, PDFs, and Office documents (docx/xlsx/pptx) in a
single monolith. The document conversion path pulls in ~2GB of heavy dependencies (docling,
torch, pymupdf, ocrmypdf, markitdown) and requires a torch DLL pre-load hack on Windows.
These dependencies bloat the agent's environment and slow startup, even when the agent never
reads a document.

Additionally, the `tools/` directory is a flat collection of 30+ files mixing tool classes
and private helpers. This makes it unclear which files belong to which tool, and complex
tools like `read` scatter their internals across the top level.

---

## Goals

1. Extract document conversion into a standalone FastAPI microservice (first "MCP-analog").
2. Restructure `tools/` so every tool lives in its own subfolder.
3. Keep a single unified `read` tool (not split into `read` + `read_document`).
4. Isolate the service client behind a dedicated module so service API changes are contained.

---

## Part 1: Tool Directory Restructure

### New structure

Every tool gets its own subfolder under `tools/`. Each subfolder contains an `__init__.py`
that re-exports the tool class(es), preserving all existing import paths unchanged.

```
tools/
  __init__.py                  # package init (unchanged)
  _path_guard.py               # shared helper — stays at top level
  _hash_cache.py               # shared helper — stays at top level
  _subagent_runner.py          # shared helper — stays at top level
  _plan_parser.py              # shared helper — stays at top level
  output_filter.py             # shared function — stays at top level
  subagent_main.py             # subagent entry point — stays at top level
  read/
    __init__.py                # re-exports ReadTool
    _read.py                   # ReadTool class
    _doc_service.py            # HTTP client for doc converter service
    _document_reader.py        # subagent orchestration (moved from tools/)
  write/
    __init__.py                # re-exports WriteTool
    _write.py                  # WriteTool class
  edit/
    __init__.py                # re-exports EditTool
    _edit.py                   # EditTool class
  bash/
    __init__.py
    _bash.py
  grep/
    __init__.py
    _grep.py
  find/
    __init__.py
    _find.py
  copy/
    __init__.py
    _copy.py
  git/
    __init__.py                # re-exports all 8 git tool classes
    _git.py                    # all git tools
  plan_mode/
    __init__.py                # re-exports EnterPlanModeTool, ExitPlanModeTool
    _plan_mode.py
  ask_user/
    __init__.py
    _ask_user.py
  skill/
    __init__.py
    _skill.py
  web_search/
    __init__.py
    _web_search.py
  web_fetch/
    __init__.py
    _web_fetch.py
  compact/
    __init__.py
    _compact.py
  switch_model/
    __init__.py
    _switch_model.py
  workflow/
    __init__.py
    _workflow.py
  reload_skills/
    __init__.py
    _reload_skills.py
  emote/
    __init__.py
    _emote.py
  explore_files/
    __init__.py
    _explore_files.py
  web_research/
    __init__.py
    _web_research.py
  show_plan/
    __init__.py
    _show_plan.py
  complete_plan/
    __init__.py
    _complete_plan.py
  cli_subagent/
    __init__.py
    _cli_subagent.py
  spawn_subagent/
    __init__.py
    _spawn_subagent.py
  extend_timeout/
    __init__.py
    _extend_timeout.py
  escalate_issue/
    __init__.py
    _escalate_issue.py
  run_skill_script/
    __init__.py
    _run_skill_script.py
  schedule_tools/
    __init__.py                # re-exports all 3 schedule tool classes
    _schedule_tools.py
```

### Import preservation

Every `__init__.py` re-exports the tool class(es):

```python
# tools/read/__init__.py
from tools.read._read import ReadTool

__all__ = ["ReadTool"]
```

This means `from tools.read import ReadTool` continues to work. **Zero changes needed in
`agent/tools.py`, test files, or any other consumer.**

### Shared helpers

Files prefixed with `_` at the `tools/` top level are shared across multiple tools and
stay put:
- `_path_guard.py` — used by read, write, edit, grep, find, copy
- `_hash_cache.py` — used by read (doc cache), output_filter
- `_subagent_runner.py` — used by spawn_subagent, cli_subagent, document_reader
- `_plan_parser.py` — used by show_plan, complete_plan
- `output_filter.py` — called from agent/loop.py
- `subagent_main.py` — subprocess entry point

### Tool-specific helpers

Private helpers that serve only one tool move into that tool's subfolder:
- `_document_reader.py` → `tools/read/_document_reader.py`
- `_pdf_convert.py` → deleted (moves to service, see Part 2)

---

## Part 2: Document Converter Service

### Service: `services/doc_converter/`

A standalone FastAPI application with its own conda environment.

```
services/doc_converter/
  environment.yml          # conda env definition (all heavy deps)
  main.py                  # FastAPI app, uvicorn entrypoint
  converter/
    __init__.py
    pdf.py                 # moved from tools/_pdf_convert.py
    office.py              # docx/xlsx/pptx via markitdown
    cache.py               # server-side content-addressed cache
  tests/
    __init__.py
    test_converter.py
    test_endpoint.py
```

**Single endpoint:**

```
POST /convert
Content-Type: multipart/form-data
Body: file (uploaded document)

Success: 200 OK
  Content-Type: text/markdown
  Body: plain markdown text

Errors: JSON body with structured error detail
  400: {"error": "...", "code": "FILE_EMPTY"}
  413: {"error": "...", "code": "FILE_TOO_LARGE"}
  422: {"error": "...", "code": "UNSUPPORTED_FORMAT"}
  500: {"error": "...", "code": "CONVERSION_FAILED"}
```

Format auto-detected from filename extension. Supported: `.pdf`, `.docx`, `.xlsx`, `.pptx`.

**Server-side cache:** content-addressed (SHA-256 of uploaded file bytes). Stored at
`services/doc_converter/.cache/<sha256>.md`. On cache hit, returns immediately without
re-running conversion.

**Lifecycle:** always-on, manual start. User runs:
```
conda run -n doc_converter python -m services.doc_converter
```
The service is not managed by DAGI.

---

## Part 3: DAGI-Side Integration

### Unified `read` tool (`tools/read/_read.py`)

The `read` tool remains a single tool. It detects the file extension and routes:
- Text files (any extension) → direct UTF-8 read (unchanged)
- Document files (`.pdf`, `.docx`, `.xlsx`, `.pptx`) → delegate to `_doc_service.py`

The routing logic is ~5 lines in `run()`:

```python
if ext in _DOC_EXTS:
    md_text = convert_document(p, self._service_url)
    # page selection, offset/limit, auto-summarization gate...
else:
    # existing text path...
```

### Service client (`tools/read/_doc_service.py`)

**This is the anti-corruption layer.** All HTTP details are encapsulated here. When the
service API evolves (new endpoints, auth, format changes), only this file changes.

```python
def convert_document(path: Path, service_url: str) -> str:
    """Upload a document to the converter service and return markdown text.

    Raises DocServiceError with code and message on failure.
    """
```

**Error handling:**
- Connection refused / timeout → `DocServiceError("CONNECTION_FAILED", "Document
  conversion service is not running at {url}. Start it with: ...")`
- 4xx/5xx from service → `DocServiceError(code, message)` with the server's error
  code and message passed through verbatim.
- The `read` tool catches `DocServiceError` and returns the message as a string to the
  LLM, which can then decide how to respond (retry, inform user, try different approach).

### Config changes

**`config.yaml`** — new `services:` block:
```yaml
services:
  doc_converter: "http://localhost:8100"
```

**`agent/config_loader.py`:**
- Add: load `services` dict from config
- Remove: `PdfConfig`, `load_pdf_config()`

**`ReadTool.__init__`:**
- Add: `service_url` parameter (passed from config at registration time)

---

## Two-Layer Cache

```
read(path="report.pdf")
    │
    ├─ hash file bytes (SHA-256)
    │
    ├─ DAGI local cache hit? ──yes──► return cached markdown (no network)
    │
    ├─ no ──► _doc_service.convert_document(path, url)
    │              │
    │              ├─ Service cache hit? ──yes──► return cached markdown (no re-convert)
    │              │
    │              ├─ no ──► convert, cache server-side, return markdown
    │              │
    │         DAGI stores response in local cache
    │
    ▼
Apply page selection / offset / limit / auto-summarization
```

- **DAGI cache** (`.dagi/hash_cache/doc_convert/`) — saves network. Per-project.
- **Service cache** (`services/doc_converter/.cache/`) — saves compute. Global.
- **Cache key**: SHA-256 of raw file bytes (both layers, same key).
- DAGI hashes the file before uploading. On local cache hit, skips upload entirely.

---

## Dependency Changes

### Removed from DAGI `pyproject.toml`

- `[project.optional-dependencies].pdf` — entire group (docling, pymupdf, ocrmypdf)
- `[project.optional-dependencies].docs` — entire group (markitdown)
- `psutil` from core deps — only consumer was `_pdf_convert.py`
- Torch pre-load hack — gone with `_pdf_convert.py`

### Added to DAGI `pyproject.toml`

- `httpx` — HTTP client for service calls (core dependency)

### Service `environment.yml`

Conda environment with all heavy deps:
- `python`, `fastapi`, `uvicorn`, `python-multipart`
- `docling`, `pymupdf`, `ocrmypdf`, `markitdown`
- `torch` (CPU-only), `psutil`

---

## Files Affected

### Tool restructure (Part 1)

| Action | Detail |
|--------|--------|
| Create | `tools/{name}/__init__.py` for each of 28 tools — re-export only |
| Move | `tools/{name}.py` → `tools/{name}/_{name}.py` for each tool |
| Move | `tools/_document_reader.py` → `tools/read/_document_reader.py` |
| Delete | All original `tools/{name}.py` files (after move) |
| Keep | Shared helpers at `tools/` level: `_path_guard.py`, `_hash_cache.py`, etc. |
| No change | `agent/tools.py` — all imports unchanged due to `__init__.py` re-exports |

### Service extraction (Part 2 + 3)

| Action | Detail |
|--------|--------|
| Create | `services/doc_converter/` — FastAPI app, converter modules, environment.yml |
| Create | `tools/read/_doc_service.py` — HTTP client for doc converter |
| Simplify | `tools/read/_read.py` — remove inline conversion, delegate to `_doc_service` |
| Delete | `tools/_pdf_convert.py` — moved to service |
| Edit | `agent/config_loader.py` — add services config, remove PdfConfig |
| Edit | `agent/tools.py` — pass service_url to ReadTool constructor |
| Edit | `pyproject.toml` — remove pdf/docs extras, add httpx |
| Update | `tests/test_read_tool.py` — remove document test cases, add service mock tests |
| Create | `services/doc_converter/tests/` — service unit tests |

---

## Testing Strategy

### Tool restructure
- Run full existing test suite after restructure — every test must pass with zero
  import changes. If any test breaks, the `__init__.py` re-export is missing something.

### Service tests (`services/doc_converter/tests/`)
- Conversion logic: mock docling/markitdown, verify markdown output
- Cache: hit/miss paths, hash correctness
- Error responses: unsupported format, empty file, conversion failure
- Endpoint integration: TestClient with real FastAPI app

### DAGI `read` tool tests (updated)
- Text files: existing passing tests (unchanged)
- Document files: mock `_doc_service.convert_document`, verify routing, cache, errors
- Service-down error message
- Page selection on cached markdown
- Auto-summarization gate

### Integration (manual / CI-optional)
- Service running locally, end-to-end: upload PDF → get markdown → read in DAGI

---

## Implementation Sequencing

These two changes should be implemented in order:

1. **Tool restructure first** — purely mechanical, zero behavior change, verifiable by
   running the full test suite. Gets the new structure in place.
2. **Service extraction second** — builds on the new structure, creates the service,
   adds `_doc_service.py` into `tools/read/`, simplifies `_read.py`.

This sequencing avoids doing both a structural move and a behavioral change in the same
step — each step is independently verifiable.

---

## What Does NOT Change

- `_document_reader.py` subagent orchestration — same behavior, moves into `tools/read/`
- `_hash_cache.py` — untouched
- `read` tool's text-file behavior — identical
- All import paths in `agent/tools.py` and tests — preserved by `__init__.py` re-exports
- Auto-summarization gate logic — same behavior
- Page selection / offset / limit — same logic
- Tool names in subagent configs — string-based, unaffected
