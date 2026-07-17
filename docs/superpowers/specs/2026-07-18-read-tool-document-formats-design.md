# ReadTool document format support (docx, xlsx, pdf) — Design

## Problem

`tools/read.py::ReadTool.run()` only supports UTF-8 text files. Any `.docx`, `.xlsx`, or `.pdf` file
either falls through to `p.read_text(encoding="utf-8")` (garbage/`UnicodeDecodeError` on binary
formats) or is explicitly blocked (images, via `_BLOCKED_EXTS`). To read the content of these
documents today, the user has to open them outside DAGI. `TODO.md`'s "PDF reading support for
`ReadTool`" backlog item (`priority:medium`) already flags this gap for PDF; this design extends the
same gap-fill to docx and xlsx.

## Goal

`read` should transparently handle `.docx`, `.xlsx`, and `.pdf` files by converting them to markdown
text in memory, then feeding that text through the tool's existing line-numbered (`cat -n` style)
output path — so the LLM sees the same output shape (`{lineno:6d}\t{content}`) regardless of source
format, with `offset`/`limit` windowing working identically across all formats.

## Approach

All three formats are converted via a single library, [`markitdown`](https://github.com/microsoft/markitdown)
(Microsoft, MIT license), which supports PDF, DOCX, and XLSX out of the box and returns a single
markdown string per document. Using one library for all three formats means one code path, one new
dependency, and one error-handling story — consistent with existing DAGI conventions (e.g.
`web_fetch.py`'s single-library-with-graceful-degradation pattern).

**PDF caveat (accepted for this design):** `markitdown`'s PDF backend (`pdfminer.six`) extracts
embedded text only — it does not OCR scanned/image-only PDFs. A scanned PDF will silently return
empty or near-empty text. OCR support (e.g. via `docling` + Tesseract) is explicitly deferred — see
Out of Scope.

**Multi-sheet XLSX:** `markitdown` renders all sheets sequentially as markdown tables by default —
this matches the desired behavior (read all sheets, no extra parameter needed).

## Architecture

### `tools/read.py`

- New module-level constant:
  ```python
  _MARKITDOWN_EXTS = {".docx", ".xlsx", ".pdf"}
  ```
- New helper function:
  ```python
  def _convert_document(p: Path) -> str:
      """Convert a docx/xlsx/pdf file to markdown text via markitdown."""
      try:
          from markitdown import MarkItDown
      except ImportError:
          raise RuntimeError(
              "markitdown is not installed. Install it with: pip install markitdown"
          )
      result = MarkItDown().convert(str(p))
      return result.text_content
  ```
- `ReadTool.run()` gains a new branch, evaluated after the existing `_BLOCKED_EXTS` gate and before
  the current UTF-8 `read_text()` call:
  ```python
  if ext in _MARKITDOWN_EXTS:
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
              f"Error: Cannot read '{p.name}' as text. The file appears to be binary "
              f"or uses an encoding other than UTF-8."
          )
  ```
  Both branches converge on the same `lines: list[str]` variable; the existing offset/limit slicing
  and `cat -n` numbering logic at the bottom of `run()` is unchanged.
- No new tool parameters. `offset`/`limit` already window over the converted line list — a
  PDF-specific `pages` parameter was considered and rejected as redundant (two mechanisms for the
  same windowing problem).
- Tool `description` updated to mention DOCX/XLSX/PDF support via markdown conversion.

### `requirements.txt`

New commented-out optional dependency section (matching the existing pattern used for web tools and
the benchmark extras):
```
# ── Optional: document reading (PDF/DOCX/XLSX) ──────────────────────────────
# Install to enable PDF, DOCX, and XLSX reading in the `read` tool.
# dagi starts and runs without this; affected files return a friendly error message.
# markitdown>=0.1.0       # Converts PDF/DOCX/XLSX to markdown text
```

## Error Handling

- **`markitdown` not installed:** `_convert_document()` raises `RuntimeError` with an actionable
  install message; caught in `run()` and returned as `"Error: Could not convert '<name>': ..."`.
- **Conversion failure (corrupt file, unsupported internal structure, etc.):** Any exception from
  `MarkItDown().convert()` is caught by the same `except Exception` in `run()` — fail loud, no partial
  output. This matches the existing `UnicodeDecodeError` handling style already in `read.py`.
- **Empty/near-empty result (e.g. scanned PDF):** Not specially detected — returns whatever
  `markitdown` produces (possibly an empty string), which is correct behavior at this scope (OCR is
  out of scope, not a bug to work around here).

## Testing

- `tests/test_read_tool.py` (existing or new): new tests for `.docx`, `.xlsx`, `.pdf` covering:
  - Successful conversion returns line-numbered markdown output (mock `MarkItDown.convert` to avoid
    a real binary fixture dependency, plus one small real fixture file per format for an integration-
    style smoke test).
  - `offset`/`limit` correctly window the converted output.
  - `ImportError` path (mock `markitdown` import failure) returns the friendly install-instruction
    error string.
  - Conversion exception (mock `.convert()` raising) returns the `"Error: Could not convert..."`
    string, not a traceback.
- Existing text-file tests in `tests/test_read_tool.py` must continue to pass unchanged — the new
  branch must not alter behavior for any extension outside `_MARKITDOWN_EXTS`.

## Out of Scope

- **OCR for scanned/image-only PDFs** (e.g. via `docling` + Tesseract). Explicitly deferred per user
  decision — most real-world PDFs in scope are text-based; OCR adds a heavy torch-based ML dependency
  and a system-level Tesseract install requirement. Tracked as a follow-up TODO item.
- **PDF page-range parameter.** Rejected — `offset`/`limit` already provide equivalent windowing over
  the converted output.
- **Other Office formats** (`.pptx`, `.doc`, `.xls`) — not requested; `markitdown` supports `.pptx`
  as well, but adding it is a one-line extension left for a future request rather than speculative
  scope now.
- **Writing/editing these formats.** `read` only; `write`/`edit` remain text-only tools.
