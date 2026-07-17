# ReadTool Document Format Support (DOCX/XLSX/PPTX) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ReadTool` (`tools/read.py`) transparently converts `.docx`, `.xlsx`, and `.pptx` files to markdown text and feeds them through the tool's existing line-numbered (`cat -n` style) output path, so the LLM reads Office documents the same way it reads any text file.

**Architecture:** A single optional dependency, [`markitdown`](https://github.com/microsoft/markitdown), converts all three formats to a markdown string. `ReadTool.run()` gains one new branch (evaluated after the existing `_BLOCKED_EXTS` gate): if the file extension is in a new `_MARKITDOWN_EXTS` set, call a new `_convert_document(p) -> str` helper instead of `p.read_text()`. Both paths converge on the same `lines: list[str]` variable, so the existing offset/limit slicing and numbering logic is untouched. `markitdown` is imported lazily inside `_convert_document()` and any failure (missing dependency or conversion error) returns a friendly `"Error: ..."` string — fail loud, no partial output, no traceback ever reaches the LLM.

**Tech Stack:** Python 3.14, `markitdown` (new optional dependency), pytest with `monkeypatch`/`sys.modules` mocking (no real binary fixtures needed). No changes to `agent/registry.py`, `_path_guard.py`, or the tool's public parameters.

Spec: `docs/superpowers/specs/2026-07-18-read-tool-document-formats-design.md`

---

### Task 1: Declare the optional `markitdown` dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the optional dependency section**

Open `requirements.txt` and add this new section at the end of the file (after the existing `# ── Optional: web tools ──` section):

```
# ── Optional: document reading (DOCX/XLSX/PPTX) ─────────────────────────────
# Install to enable DOCX, XLSX, and PPTX reading in the `read` tool.
# dagi starts and runs without this; affected files return a friendly error message.
# markitdown>=0.1.0       # Converts DOCX/XLSX/PPTX to markdown text
```

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "docs: declare markitdown as an optional dependency for ReadTool"
```

---

### Task 2: Write failing tests for document-format conversion

**Files:**
- Create: `tests/test_read_tool.py`

No test file for `ReadTool` exists yet (confirmed via `grep -r ReadTool tests/` — only incidental imports in `tests/test_tool_filter.py` and `tests/test_scope_tools.py`, no dedicated test file). This task creates one.

The tests use a **fake `markitdown` module** injected into `sys.modules` via `monkeypatch` — this means the tests never need `markitdown` actually installed, never touch a real binary `.docx`/`.xlsx`/`.pptx` file, and run identically in any environment. `ReadTool._convert_document()` (to be added in Task 3) does `from markitdown import MarkItDown` *inside* the function body, so patching `sys.modules["markitdown"]` before calling `tool.run()` is sufficient — no need to patch anything inside `tools.read` itself.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_read_tool.py`:

```python
"""tests/test_read_tool.py — Unit tests for tools/read.py::ReadTool document-format support."""
from __future__ import annotations

import sys
import types
from pathlib import Path

from tools.read import ReadTool


def _numbered(lines: list[str], start: int = 1) -> str:
    """Build the same `cat -n` style output ReadTool.run() produces, for assertions."""
    return "\n".join(f"{i:6d}\t{line}" for i, line in enumerate(lines, start))


def _install_fake_markitdown(monkeypatch, *, text: str | None = None, error: Exception | None = None) -> None:
    """Install a fake `markitdown` module in sys.modules for the duration of one test.

    Pass `text` for a successful conversion, or `error` to simulate MarkItDown().convert()
    raising. monkeypatch automatically restores the real sys.modules state after each test.
    """
    class _FakeResult:
        def __init__(self, content: str) -> None:
            self.text_content = content

    class _FakeMarkItDown:
        def convert(self, path: str) -> _FakeResult:
            if error is not None:
                raise error
            return _FakeResult(text if text is not None else "")

    fake_module = types.ModuleType("markitdown")
    fake_module.MarkItDown = _FakeMarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake_module)


def _make_tool(tmp_path: Path) -> ReadTool:
    return ReadTool(cwd=tmp_path, allowed_roots=[tmp_path])


class TestDocumentFormatConversion:
    def test_docx_file_returns_line_numbered_markdown(self, tmp_path, monkeypatch):
        _install_fake_markitdown(monkeypatch, text="# Title\n\nBody text.")
        (tmp_path / "report.docx").write_bytes(b"fake docx bytes")  # never actually parsed
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.docx")

        assert result == _numbered(["# Title", "", "Body text."])

    def test_xlsx_file_returns_line_numbered_markdown(self, tmp_path, monkeypatch):
        _install_fake_markitdown(monkeypatch, text="| A | B |\n| --- | --- |\n| 1 | 2 |")
        (tmp_path / "data.xlsx").write_bytes(b"fake xlsx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="data.xlsx")

        assert result == _numbered(["| A | B |", "| --- | --- |", "| 1 | 2 |"])

    def test_pptx_file_returns_line_numbered_markdown(self, tmp_path, monkeypatch):
        _install_fake_markitdown(monkeypatch, text="## Slide 1\n\nWelcome")
        (tmp_path / "deck.pptx").write_bytes(b"fake pptx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="deck.pptx")

        assert result == _numbered(["## Slide 1", "", "Welcome"])

    def test_offset_and_limit_window_the_converted_output(self, tmp_path, monkeypatch):
        _install_fake_markitdown(monkeypatch, text="line1\nline2\nline3\nline4")
        (tmp_path / "report.docx").write_bytes(b"fake docx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.docx", offset=2, limit=2)

        assert result == _numbered(["line2", "line3"], start=2)

    def test_missing_markitdown_dependency_returns_friendly_error(self, tmp_path, monkeypatch):
        # Setting sys.modules["markitdown"] = None forces `from markitdown import ...`
        # to raise ImportError, regardless of whether markitdown is really installed.
        monkeypatch.setitem(sys.modules, "markitdown", None)
        (tmp_path / "report.docx").write_bytes(b"fake docx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.docx")

        assert result.startswith("Error: Could not convert 'report.docx':")
        assert "pip install markitdown" in result

    def test_conversion_exception_returns_friendly_error_not_traceback(self, tmp_path, monkeypatch):
        _install_fake_markitdown(monkeypatch, error=RuntimeError("corrupt zip"))
        (tmp_path / "report.docx").write_bytes(b"fake docx bytes")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.docx")

        assert result == "Error: Could not convert 'report.docx': corrupt zip"

    def test_text_files_are_unaffected_by_the_new_branch(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hello\nworld", encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt")

        assert result == _numbered(["hello", "world"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py -v`

Expected: The first three tests (`test_docx_file_...`, `test_xlsx_file_...`, `test_pptx_file_...`) and `test_offset_and_limit_window_...` FAIL with an assertion mismatch — today's `ReadTool` reads the raw bytes as literal UTF-8 text (e.g. `"fake docx bytes"` as a single line) instead of using the mocked markdown conversion. `test_missing_markitdown_dependency_...` and `test_conversion_exception_...` FAIL because the returned string doesn't start with `"Error: Could not convert"` (today's code doesn't recognize `.docx` as special at all). `test_text_files_are_unaffected_...` should already PASS (it exercises no new code).

- [ ] **Step 3: Commit**

```bash
git add tests/test_read_tool.py
git commit -m "test: add failing tests for ReadTool docx/xlsx/pptx conversion"
```

---

### Task 3: Implement document conversion in `ReadTool`

**Files:**
- Modify: `tools/read.py`

- [ ] **Step 1: Add the `_MARKITDOWN_EXTS` constant and `_convert_document()` helper**

In `tools/read.py`, after the existing `_BLOCKED_EXTS = _IMAGE_EXTS.copy()` line (line 21) and before `class ReadTool(BaseTool):`, add:

```python
# Office document formats converted to markdown via the optional `markitdown`
# dependency before being fed through the same line-numbered text path as any
# other file. Install with: pip install markitdown (see requirements.txt).
_MARKITDOWN_EXTS = {".docx", ".xlsx", ".pptx"}


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

- [ ] **Step 2: Update the tool description**

Replace the existing `description` string:

```python
    description = (
        "Read the contents of a file. Supports all text files (any extension) — "
        "attempts UTF-8 decoding. Defaults to first 2000 lines. "
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
        "attempts UTF-8 decoding. Also supports .docx, .xlsx, and .pptx (converted "
        "to markdown text via the optional `markitdown` dependency). "
        "Defaults to first 2000 lines. "
        "Use offset/limit for large files. Accepts both relative paths "
        "(resolved from the project root) and absolute paths. "
        "Output uses `cat -n` style: each line is prefixed with its 1-indexed "
        "line number followed by a tab — the number is not part of the file content. "
        "For large-scale codebase exploration, prefer `explore_files`."
    )
```

- [ ] **Step 3: Branch in `run()` on the new extension set**

Replace the existing body from the blocked-extension gate onward:

```python
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return (
                f"Error: Cannot read '{p.name}' as text. The file appears to be binary "
                f"or uses an encoding other than UTF-8."
            )
```

with:

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

The rest of `run()` (the `start = max(0, offset - 1)` slicing and the final `"\n".join(...)` numbering) is unchanged — both branches leave `lines: list[str]` set before reaching it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py -v`

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/read.py
git commit -m "feat: ReadTool converts docx/xlsx/pptx to markdown via markitdown"
```

---

### Task 4: Full regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `conda run -n dagi python -m pytest tests/ -q --ignore=tests/dagi_eval`

Expected: All tests pass, no regressions. (`tests/dagi_eval/` is excluded per existing project convention — it has a pre-existing unrelated `numpy` import error in this conda env, documented in `AGENTS.md`'s Notes & Terms.)

- [ ] **Step 2 (optional manual smoke test): verify against a real file**

This step requires `markitdown` actually installed — it is optional and does not block completion of this plan, since `markitdown` is an optional dependency by design.

```bash
conda run -n dagi pip install markitdown
```

Create or locate any small real `.docx`, `.xlsx`, or `.pptx` file, then run:

```bash
conda run -n dagi python -c "from pathlib import Path; from tools.read import ReadTool; t = ReadTool(cwd=Path('.'), allowed_roots=[Path('.').resolve()]); print(t.run(path='<path-to-your-file>'))"
```

Expected: Line-numbered markdown output reflecting the real document's content (headings, paragraphs, tables). If `markitdown` is not installed, skip this step — the mocked tests in Task 2 already exercise every code path.

---

### Task 5: Update project documentation

**Files:**
- Modify: `README.md`
- Modify: `TODO.md`
- Modify: `AGENTS.md` (via the `update-project-context` skill)

- [ ] **Step 1: Update the Tools table in `README.md`**

In `README.md`, find the `### Tools` table (around line 562) and replace this row:

```
| `read` | Read a text file (paginated) or image (base64). Pass `path`, optional `offset`/`limit` |
```

with:

```
| `read` | Read a text file (paginated), image (base64), or DOCX/XLSX/PPTX (converted to markdown via the optional `markitdown` dependency). Pass `path`, optional `offset`/`limit` |
```

- [ ] **Step 2: Add a Completed entry to `TODO.md`**

In `TODO.md`, add this entry at the top of the `## Completed` section (above the existing most-recent entry):

```markdown
- **`read` tool gains DOCX/XLSX/PPTX support via markitdown** · `done` · `2026-07-18`
  - **Problem:** `ReadTool` (`tools/read.py`) only supported UTF-8 text files — Office documents had to be opened outside DAGI to read their content.
  - **Fix:** New `_MARKITDOWN_EXTS = {".docx", ".xlsx", ".pptx"}` set and `_convert_document()` helper in `tools/read.py` convert these formats to markdown via the optional `markitdown` library, then feed the result through the existing offset/limit + `cat -n` line-numbering path unchanged — both the text and document branches converge on a plain `list[str]` before that shared logic runs. PDF was evaluated and deliberately excluded: `markitdown`'s PDF backend has no OCR for scanned pages and documented table-fidelity gaps on complex tables — it needs its own design pass (see the PDF item in Work Queue → Features, updated to reflect this).
  - **Test:** `tests/test_read_tool.py` (new, 7 tests) — mocked `markitdown` conversion via `sys.modules` injection (no real binary fixtures needed) covering success per format, offset/limit windowing, missing-dependency error, conversion-exception error, and confirming existing text-file behavior is unchanged. Full suite `pytest tests/ -q --ignore=tests/dagi_eval` — no regressions.
  - Spec: `docs/superpowers/specs/2026-07-18-read-tool-document-formats-design.md`. Plan: `docs/superpowers/plans/2026-07-18-read-tool-document-formats.md`.
```

Then find the existing PDF backlog item under `### 🟢 Features` (search for `**PDF reading support for `ReadTool`**`) and replace it:

```markdown
- **PDF reading support for `ReadTool`** · `priority:medium` · `effort:S`
  - Add PDF support using `PyMuPDF` (fitz) with page range support. Fall back gracefully if not installed.
  - **Source:** `_todo/todo_2026-06-19.md` D1
```

with:

```markdown
- **PDF reading support for `ReadTool`** · `priority:medium` · `effort:S`
  - DOCX/XLSX/PPTX support shipped 2026-07-18 via `markitdown` (see Completed). PDF was deliberately excluded from that work — `markitdown`'s PDF backend has no OCR for scanned pages and documented table-fidelity gaps on complex tables. Needs its own design pass to decide OCR/quality trade-offs (e.g. `docling`+Tesseract vs. plain `markitdown`) before implementing.
  - **Source:** `_todo/todo_2026-06-19.md` D1
```

- [ ] **Step 3: Refresh `AGENTS.md`**

Invoke the `update-project-context` skill to refresh `AGENTS.md`'s Key Files & Directories, Errors Log (if any gotchas were hit during implementation), and Notes & Terms sections to reflect the new `_MARKITDOWN_EXTS`/`_convert_document()` addition to `tools/read.py`.

- [ ] **Step 4: Commit**

```bash
git add README.md TODO.md AGENTS.md
git commit -m "docs: record ReadTool docx/xlsx/pptx support in README/TODO/AGENTS"
```
