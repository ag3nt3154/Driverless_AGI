# ReadTool document format support (docx, xlsx, pptx) — Design

## Problem

`tools/read.py::ReadTool.run()` only supports UTF-8 text files. Any `.docx`, `.xlsx`, or `.pptx` file
either falls through to `p.read_text(encoding="utf-8")` (garbage/`UnicodeDecodeError` on binary
formats) or is explicitly blocked (images, via `_BLOCKED_EXTS`). To read the content of these
documents today, the user has to open them outside DAGI.

## Goal

`read` should transparently handle `.docx`, `.xlsx`, and `.pptx` files by converting them to markdown
text in memory, then feeding that text through the tool's existing line-numbered (`cat -n` style)
output path — so the LLM sees the same output shape (`{lineno:6d}\t{content}`) regardless of source
format, with `offset`/`limit` windowing working identically across all formats.

## Approach

All three formats are converted via a single library, [`markitdown`](https://github.com/microsoft/markitdown)
(Microsoft, MIT license), which supports DOCX, XLSX, and PPTX out of the box and returns a single
markdown string per document. Using one library for all three formats means one code path, one new
dependency, and one error-handling story — consistent with existing DAGI conventions (e.g.
`web_fetch.py`'s single-library-with-graceful-degradation pattern).

**Why these three formats, and not PDF:** All three are structured XML formats under the hood
(Office Open XML) — `markitdown` delegates DOCX to `mammoth` (structured document → HTML → markdown)
and XLSX/PPTX to format-native parsers (`openpyxl`-style / slide XML), so conversion fidelity is
governed by well-defined document structure, not visual-layout heuristics. PDF was evaluated and
explicitly deferred: `markitdown`'s PDF backend (hybrid `pdfplumber`/`pdfminer.six`) extracts text via
layout heuristics, has no OCR for scanned pages, and has documented table-fidelity gaps on complex
tables (cell content can collapse into run-on text with no row/column structure recoverable). PDF
deserves its own design pass once we decide on a quality bar (plain `markitdown`, vs. a heavier
layout-aware tool). Tracked as a follow-up TODO item.

**Multi-sheet XLSX:** `markitdown` renders all sheets sequentially as markdown tables by default —
this matches the desired behavior (read all sheets, no extra parameter needed).

**DOCX/PPTX table caveat:** Simple tables convert cleanly to markdown pipe-table syntax. Merged/
spanned cells (`vMerge` in DOCX, merged cells in PPTX tables) don't have a markdown-table equivalent
and may render misaligned or duplicated — a known upstream limitation, not something this design
works around.

## Architecture

### `tools/read.py`

- New module-level constant:
  ```python
  _MARKITDOWN_EXTS = {".docx", ".xlsx", ".pptx"}
  ```
- New helper function:
  ```python
  def _convert_document(p: Path) -> str:
      """Convert a docx/xlsx/pptx file to markdown text via markitdown."""
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
- No new tool parameters. `offset`/`limit` already window over the converted line list.
- Tool `description` updated to mention DOCX/XLSX/PPTX support via markdown conversion.

### `requirements.txt`

New commented-out optional dependency section (matching the existing pattern used for web tools and
the benchmark extras):
```
# ── Optional: document reading (DOCX/XLSX/PPTX) ─────────────────────────────
# Install to enable DOCX, XLSX, and PPTX reading in the `read` tool.
# dagi starts and runs without this; affected files return a friendly error message.
# markitdown>=0.1.0       # Converts DOCX/XLSX/PPTX to markdown text
```

## Error Handling

- **`markitdown` not installed:** `_convert_document()` raises `RuntimeError` with an actionable
  install message; caught in `run()` and returned as `"Error: Could not convert '<name>': ..."`.
- **Conversion failure (corrupt file, unsupported internal structure, etc.):** Any exception from
  `MarkItDown().convert()` is caught by the same `except Exception` in `run()` — fail loud, no partial
  output. This matches the existing `UnicodeDecodeError` handling style already in `read.py`.

## Testing

- `tests/test_read_tool.py` (existing or new): new tests for `.docx`, `.xlsx`, `.pptx` covering:
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

- **PDF support.** Deferred to a separate design — needs its own decision on OCR (scanned PDFs) and
  table-fidelity trade-offs (plain `markitdown` vs. heavier layout-aware tools like `docling`/`marker`).
  `TODO.md`'s existing "PDF reading support for `ReadTool`" backlog item remains open, now pointing at
  this follow-up design rather than this implementation.
- **OCR for scanned/image-only documents.** Not applicable to DOCX/XLSX/PPTX (no scanned-image
  variant of these formats in scope); revisit if/when PDF is designed.
- **Other Office formats** (`.doc`, `.xls`, `.ppt` — legacy binary formats). Not requested; `markitdown`
  support for legacy binary Office formats is less consistent than the modern XML-based formats in
  scope here.
- **Writing/editing these formats.** `read` only; `write`/`edit` remain text-only tools.
