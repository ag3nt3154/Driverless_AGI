# Hashline Read/Edit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace DAGI's substring-based `edit` and `cat -n` `read` with hash-anchored line addressing, so edits target a verified `LINE#HASH` anchor instead of an exact text match.

**Architecture:** One new shared helper `tools/_hashline.py` owns the anchor format — hashing, table construction, rendering, parsing, and resolution. `read`, `edit`, and `grep` all consume it, so an anchor from any of the three is interchangeable. Validation is stateless: `edit` rebuilds the anchor table from disk on every call and fails loud on mismatch, which means no snapshots and no cross-process state.

**Tech Stack:** Python 3, stdlib `hashlib.blake2b`, pytest, ripgrep (`rg --json`). All commands run in the `dagi` conda env.

**Spec:** `docs/superpowers/specs/2026-07-26-hashline-read-edit-design.md` (commit `5f6755a`)

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/_hashline.py` (create) | Anchor format single source of truth: `line_hash`, `build_anchors`, `format_region`, `compute_affected_range`, `parse_anchor`, `resolve_anchor`, `contains_display_prefix`, `AnchorError` |
| `tools/read/_read.py` (modify) | Emit `LINE#HASH:` output; disclose document cache path in header |
| `tools/edit/_edit.py` (rewrite) | Batched anchored operations |
| `tools/grep/_grep.py` (modify) | Structured match extraction via `rg --json`; emit anchors |
| `tests/test_hashline.py` (create) | Hash and format unit tests |
| `tests/test_edit_tool.py` (create) | Edit behaviour — currently zero coverage |
| `tests/test_grep_tool.py` (create) | Grep anchors and degrade path |
| `tests/test_read_tool.py` (modify) | Format assertions |
| `tests/test_hashline_properties.py` (create) | Uniqueness, cross-tool agreement, bottom-up equivalence |

Constructor signatures do not change, so `agent/tools.py` and `agent/subagent_tools.py` are untouched.

---

## Task 1: Hash core

**Files:**
- Create: `tools/_hashline.py`
- Test: `tests/test_hashline.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_hashline.py`:

```python
from tools import _hashline as H


class TestLineHash:
    def test_is_deterministic(self):
        assert H.line_hash("a", "b", "c") == H.line_hash("a", "b", "c")

    def test_length_is_three(self):
        assert len(H.line_hash("a", "b", "c")) == 3

    def test_uses_alphabet_only(self):
        h = H.line_hash("x", "y", "z")
        assert all(ch in H._ALPHABET for ch in h)

    def test_neighbours_change_the_hash(self):
        assert H.line_hash("a", "same", "c") != H.line_hash("q", "same", "c")
        assert H.line_hash("a", "same", "c") != H.line_hash("a", "same", "q")

    def test_retry_changes_the_hash(self):
        assert H.line_hash("a", "b", "c", 0) != H.line_hash("a", "b", "c", 1)


class TestBuildAnchors:
    def test_one_anchor_per_line(self):
        assert len(H.build_anchors(["a", "b", "c"])) == 3

    def test_empty_file_gives_no_anchors(self):
        assert H.build_anchors([]) == []

    def test_boundary_lines_use_empty_neighbours(self):
        anchors = H.build_anchors(["only"])
        assert anchors[0] == H.line_hash("", "only", "")

    def test_identical_lines_get_distinct_anchors(self):
        anchors = H.build_anchors(["}", "}", "}", "}"])
        assert len(set(anchors)) == 4

    def test_all_anchors_unique_on_repetitive_file(self):
        anchors = H.build_anchors([""] * 200)
        assert len(set(anchors)) == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_hashline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools._hashline'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/_hashline.py`:

```python
"""Hash-anchored line addressing shared by read, edit, and grep.

Single source of truth for the LINE#HASH anchor format. No tool computes a
line hash independently — an anchor from any tool must resolve in any other.
"""
from __future__ import annotations

import hashlib

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
HASH_LEN = 3


def line_hash(prev: str, curr: str, nxt: str, retry: int = 0) -> str:
    """Hash a line in the context of its immediate neighbours.

    Six bits per character are masked off the digest rather than base-converting,
    so HASH_LEN is a pure knob on how many low bits are retained.
    """
    payload = f"{prev}\0{curr}\0{nxt}"
    if retry:
        payload += f":R{retry}"
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return "".join(_ALPHABET[(value >> (6 * i)) & 63] for i in range(HASH_LEN))


def build_anchors(lines: list[str]) -> list[str]:
    """Return one unique hash per line, index i holding the hash for line i+1.

    Collisions are resolved by incrementing a retry counter until the hash is
    unique within the file, so every line is independently addressable.
    """
    seen: set[str] = set()
    out: list[str] = []
    for i, curr in enumerate(lines):
        prev = lines[i - 1] if i > 0 else ""
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        retry = 0
        h = line_hash(prev, curr, nxt)
        while h in seen:
            retry += 1
            h = line_hash(prev, curr, nxt, retry)
        seen.add(h)
        out.append(h)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_hashline.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add tools/_hashline.py tests/test_hashline.py
git commit -m "feat: add hashline core hashing with perfect-hash collision retry"
```

---

## Task 2: Anchor rendering

**Files:**
- Modify: `tools/_hashline.py`
- Test: `tests/test_hashline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hashline.py`:

```python
class TestFormatRegion:
    def test_renders_anchor_prefixed_lines(self):
        lines = ["alpha", "beta", "gamma"]
        anchors = H.build_anchors(lines)
        out = H.format_region(lines, anchors, 1, 3)
        assert out.splitlines() == [
            f"1#{anchors[0]}:alpha",
            f"2#{anchors[1]}:beta",
            f"3#{anchors[2]}:gamma",
        ]

    def test_line_numbers_right_aligned_to_end_width(self):
        lines = [f"L{i}" for i in range(1, 11)]
        anchors = H.build_anchors(lines)
        out = H.format_region(lines, anchors, 9, 10).splitlines()
        assert out[0].startswith(" 9#")
        assert out[1].startswith("10#")

    def test_renders_a_subrange_only(self):
        lines = ["a", "b", "c", "d"]
        anchors = H.build_anchors(lines)
        assert len(H.format_region(lines, anchors, 2, 3).splitlines()) == 2

    def test_preserves_content_containing_colons(self):
        lines = ["key: value"]
        anchors = H.build_anchors(lines)
        assert H.format_region(lines, anchors, 1, 1).endswith(":key: value")


class TestComputeAffectedRange:
    def test_pads_by_context_lines(self):
        assert H.compute_affected_range(5, 5, 20) == (3, 7)

    def test_clamps_to_file_bounds(self):
        assert H.compute_affected_range(1, 1, 3) == (1, 3)

    def test_returns_none_when_span_exceeds_budget(self):
        assert H.compute_affected_range(1, 40, 100) is None

    def test_returns_none_when_bounds_missing(self):
        assert H.compute_affected_range(None, 5, 10) is None
        assert H.compute_affected_range(5, None, 10) is None

    def test_returns_none_on_degenerate_range(self):
        assert H.compute_affected_range(5, 0, 10) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_hashline.py -k "FormatRegion or AffectedRange" -v`
Expected: FAIL — `AttributeError: module 'tools._hashline' has no attribute 'format_region'`

- [ ] **Step 3: Write minimal implementation**

Add to `tools/_hashline.py`, after `build_anchors`:

```python
ANCHOR_CONTEXT_LINES = 2
ANCHOR_MAX_OUTPUT_LINES = 12
ANCHOR_TEXT_BUDGET_BYTES = 50 * 1024
ANCHORS_OMITTED_TEXT = "Anchors omitted; use read for subsequent edits."


def format_region(
    lines: list[str],
    anchors: list[str],
    start: int,
    end: int,
) -> str:
    """Render lines start..end (1-indexed, inclusive) as LINE#HASH:content."""
    width = len(str(end))
    return "\n".join(
        f"{i:>{width}}#{anchors[i - 1]}:{lines[i - 1]}"
        for i in range(start, end + 1)
    )


def compute_affected_range(
    first_changed: int | None,
    last_changed: int | None,
    total_lines: int,
) -> tuple[int, int] | None:
    """Context window around a change, or None if unbounded or over budget."""
    if first_changed is None or last_changed is None:
        return None
    start = max(1, first_changed - ANCHOR_CONTEXT_LINES)
    end = min(total_lines, last_changed + ANCHOR_CONTEXT_LINES)
    if end < start or (end - start + 1) > ANCHOR_MAX_OUTPUT_LINES:
        return None
    return start, end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_hashline.py -v`
Expected: PASS, 19 tests

- [ ] **Step 5: Commit**

```bash
git add tools/_hashline.py tests/test_hashline.py
git commit -m "feat: add hashline region rendering and affected-range window"
```

---

## Task 3: Anchor parsing and resolution

**Files:**
- Modify: `tools/_hashline.py`
- Test: `tests/test_hashline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hashline.py`:

```python
import pytest


class TestParseAnchor:
    def test_parses_line_and_hash(self):
        assert H.parse_anchor("18#aB3") == (18, "aB3")

    def test_tolerates_surrounding_whitespace(self):
        assert H.parse_anchor("  7#xY-  ") == (7, "xY-")

    def test_rejects_missing_hash(self):
        with pytest.raises(H.AnchorError) as exc:
            H.parse_anchor("18")
        assert exc.value.code == "E_INVALID_ANCHOR"

    def test_rejects_wrong_hash_length(self):
        with pytest.raises(H.AnchorError) as exc:
            H.parse_anchor("18#aB")
        assert exc.value.code == "E_INVALID_ANCHOR"


class TestResolveAnchor:
    def test_returns_zero_based_index(self):
        anchors = H.build_anchors(["a", "b", "c"])
        assert H.resolve_anchor(f"2#{anchors[1]}", anchors) == 1

    def test_stale_hash_raises_stale_anchor(self):
        anchors = H.build_anchors(["a", "b", "c"])
        with pytest.raises(H.AnchorError) as exc:
            H.resolve_anchor(f"2#{anchors[0]}", anchors)
        assert exc.value.code == "E_STALE_ANCHOR"
        assert "re-read" in exc.value.message

    def test_out_of_range_line_raises_invalid_anchor(self):
        anchors = H.build_anchors(["a"])
        with pytest.raises(H.AnchorError) as exc:
            H.resolve_anchor(f"9#{anchors[0]}", anchors)
        assert exc.value.code == "E_INVALID_ANCHOR"


class TestContainsDisplayPrefix:
    def test_detects_anchor_prefix_in_content(self):
        assert H.contains_display_prefix(["12#aB3:x = 1"]) is not None

    def test_detects_diff_hunk_header(self):
        assert H.contains_display_prefix(["@@ -1,2 +1,3 @@"]) is not None

    def test_allows_yaml_frontmatter_delimiter(self):
        assert H.contains_display_prefix(["---"]) is None

    def test_allows_ordinary_content(self):
        assert H.contains_display_prefix(["def f():", "    return 1"]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_hashline.py -k "ParseAnchor or ResolveAnchor or DisplayPrefix" -v`
Expected: FAIL — `AttributeError: module 'tools._hashline' has no attribute 'AnchorError'`

- [ ] **Step 3: Write minimal implementation**

Add `import re` to the imports in `tools/_hashline.py`, then append:

```python
_ANCHOR_RE = re.compile(rf"^(\d+)#([A-Za-z0-9_-]{{{HASH_LEN}}})$")
_ANCHOR_PREFIX_RE = re.compile(rf"^\s*\d+#[A-Za-z0-9_-]{{{HASH_LEN}}}:")
_HUNK_RE = re.compile(r"^@@ .* @@")


class AnchorError(Exception):
    """Raised when an anchor is malformed, out of range, or stale."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def parse_anchor(anchor: str) -> tuple[int, str]:
    match = _ANCHOR_RE.match(anchor.strip())
    if not match:
        raise AnchorError(
            "E_INVALID_ANCHOR",
            f"malformed anchor {anchor!r}; expected LINE#HASH, e.g. 18#aB3",
        )
    return int(match.group(1)), match.group(2)


def resolve_anchor(anchor: str, anchors: list[str]) -> int:
    """Resolve an anchor to a 0-based line index against a fresh anchor table."""
    lineno, want = parse_anchor(anchor)
    if lineno < 1 or lineno > len(anchors):
        raise AnchorError(
            "E_INVALID_ANCHOR",
            f"line {lineno} out of range; file has {len(anchors)} lines",
        )
    got = anchors[lineno - 1]
    if got != want:
        raise AnchorError(
            "E_STALE_ANCHOR",
            f"anchor {anchor} no longer matches; line {lineno} is now "
            f"{lineno}#{got}. Re-read the file to get current anchors.",
        )
    return lineno - 1


def contains_display_prefix(lines: list[str]) -> str | None:
    """Return the first line that looks like tool display output, else None.

    Only anchor prefixes and diff hunk headers are treated as suspicious.
    Bare `---` and `+++` are deliberately allowed: they are legitimate content
    in this repo (YAML frontmatter, markdown horizontal rules).
    """
    for line in lines:
        if _ANCHOR_PREFIX_RE.match(line) or _HUNK_RE.match(line):
            return line
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_hashline.py -v`
Expected: PASS, 30 tests

- [ ] **Step 5: Commit**

```bash
git add tools/_hashline.py tests/test_hashline.py
git commit -m "feat: add hashline anchor parsing, resolution, and display-prefix guard"
```

---

## Task 4: `read` emits anchors

**Files:**
- Modify: `tools/read/_read.py:166-198`
- Test: `tests/test_read_tool.py:7-8` (helper), plus assertions throughout

- [ ] **Step 1: Update the test helper to expect anchors**

Replace the `_numbered` helper at `tests/test_read_tool.py:7-8` with:

```python
from tools import _hashline as H


def _anchored(all_lines, start=1, end=None):
    """Render the expected read output for lines start..end of all_lines."""
    end = len(all_lines) if end is None else end
    anchors = H.build_anchors(all_lines)
    return H.format_region(all_lines, anchors, start, end)
```

Then update the two existing call sites:

```python
    def test_reads_text_file(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello\nworld", encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt")

        assert result == _anchored(["hello", "world"])

    def test_offset_and_limit(self, tmp_path):
        all_lines = [f"line{i}" for i in range(1, 11)]
        f = tmp_path / "notes.txt"
        f.write_text("\n".join(all_lines), encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt", offset=3, limit=2)

        assert result == _anchored(all_lines, start=3, end=4)
```

Add a new test asserting the windowing invariant:

```python
    def test_windowed_read_anchors_match_whole_file_anchors(self, tmp_path):
        all_lines = [f"line{i}" for i in range(1, 21)]
        f = tmp_path / "notes.txt"
        f.write_text("\n".join(all_lines), encoding="utf-8")
        tool = _make_tool(tmp_path)

        windowed = tool.run(path="notes.txt", offset=15, limit=3)
        anchors = H.build_anchors(all_lines)

        assert f"#{anchors[14]}:line15" in windowed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py -k TextFileReading -v`
Expected: FAIL — output still uses `{:6d}\t` numbering

- [ ] **Step 3: Write minimal implementation**

In `tools/read/_read.py`, add the import:

```python
from tools import _hashline as H
```

Replace lines 167-186 (the `start`/`selected`/`numbered` block and the `full_text`
construction inside the summarisation gate) with:

```python
        anchors = H.build_anchors(lines)
        start = max(1, offset)
        end = min(len(lines), start + limit - 1)
        numbered = H.format_region(lines, anchors, start, end) if lines else ""

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
            full_text = H.format_region(lines, anchors, 1, len(lines)) if lines else ""
            estimated_tokens = len(full_text) // _CHARS_PER_TOKEN
```

Leave the remainder of the summarisation gate and the trailing `return raw_result` unchanged.

Update the `description` string at `tools/read/_read.py:66-68`, replacing the `cat -n` sentence with:

```python
        "Output is anchored: each line is prefixed with `LINE#HASH:` where LINE "
        "is the 1-indexed line number and HASH verifies the line's content. "
        "Pass the whole `LINE#HASH` token (e.g. `18#aB3`) as an anchor to `edit`. "
        "The prefix is not part of the file content. "
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py -v`
Expected: PASS — all existing document/error tests still green

- [ ] **Step 5: Commit**

```bash
git add tools/read/_read.py tests/test_read_tool.py
git commit -m "feat: emit LINE#HASH anchors from read tool"
```

---

## Task 5: `read` discloses the document cache path

**Files:**
- Modify: `tools/read/_read.py:136-155`
- Test: `tests/test_read_tool.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_read_tool.py`:

```python
class TestDocumentCacheDisclosure:
    def test_pdf_header_discloses_editable_cache_path(self, tmp_path):
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        tool = _make_tool(tmp_path)

        with patch(
            "tools.read._read.convert_document",
            return_value="<!-- Page 1 -->\nhello",
        ):
            result = tool.run(path="report.pdf")

        assert "editable:" in result
        assert ".dagi" in result
        assert result.splitlines()[0].endswith("]")

    def test_docx_header_discloses_editable_cache_path(self, tmp_path):
        f = tmp_path / "notes.docx"
        f.write_bytes(b"PK fake docx")
        tool = _make_tool(tmp_path)

        with patch("tools.read._read.convert_document", return_value="hello"):
            result = tool.run(path="notes.docx")

        assert result.startswith("[notes.docx | editable: ")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py -k DocumentCacheDisclosure -v`
Expected: FAIL — no `editable:` in output; `.docx` currently produces no header at all

- [ ] **Step 3: Write minimal implementation**

Add to `tools/read/_doc_service.py`, after the `_TIMEOUT` constant:

```python
def cache_path_for(path: Path, project_path: Path) -> Path:
    """Path of the converted-markdown cache entry for a source document."""
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return project_path / ".dagi" / "hash_cache" / _DOC_CACHE_SUBDIR / f"{content_hash}.md"
```

Refactor `convert_document` to use it, replacing lines 48-55 with:

```python
    cache_file = cache_path_for(path, project_path)
    cache_dir = cache_file.parent
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    file_bytes = path.read_bytes()
```

In `tools/read/_read.py`, update the import:

```python
from tools.read._doc_service import cache_path_for, convert_document, DocServiceError
```

Replace the header construction at lines 147-154 with:

```python
            editable = cache_path_for(p, self._project_path)
            try:
                editable_str = str(editable.relative_to(self._project_path))
            except ValueError:
                editable_str = str(editable)

            if ext == ".pdf":
                total_pages = md_text.count("<!-- Page ")
                if pages:
                    md_text = _select_pages(md_text, pages)
                header = f"[PDF: {p.name} | {total_pages} pages"
                if pages:
                    header += f" | showing pages {pages}"
                header += f" | editable: {editable_str}]"
            else:
                header = f"[{p.name} | editable: {editable_str}]"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/read/_read.py tools/read/_doc_service.py tests/test_read_tool.py
git commit -m "feat: disclose editable document cache path in read header"
```

---

## Task 6: `edit` skeleton with `replace`

**Files:**
- Rewrite: `tools/edit/_edit.py`
- Test: `tests/test_edit_tool.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_edit_tool.py`:

```python
from pathlib import Path

from tools import _hashline as H
from tools.edit import EditTool


def _make_tool(tmp_path):
    return EditTool(cwd=tmp_path, allowed_roots=[tmp_path])


def _write(tmp_path, name, lines):
    f = tmp_path / name
    f.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return f


def _anchor_for(lines, lineno):
    return f"{lineno}#{H.build_anchors(lines)[lineno - 1]}"


class TestReplace:
    def test_replaces_a_single_line(self, tmp_path):
        lines = ["alpha", "beta", "gamma"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 2), "lines": ["BETA"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["alpha", "BETA", "gamma"]

    def test_replaces_an_inclusive_range(self, tmp_path):
        lines = ["a", "b", "c", "d"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[{
            "op": "replace",
            "pos": _anchor_for(lines, 2),
            "end": _anchor_for(lines, 3),
            "lines": ["X"],
        }])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "X", "d"]

    def test_replace_with_no_lines_deletes(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 2), "lines": []},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "c"]

    def test_targets_a_repeated_line_unambiguously(self, tmp_path):
        lines = ["}", "}", "}"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 2), "lines": ["MIDDLE"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["}", "MIDDLE", "}"]


class TestStaleAnchor:
    def test_stale_anchor_reports_error_and_leaves_file_intact(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)
        stale = _anchor_for(lines, 1).replace("1#", "2#")

        result = tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": stale, "lines": ["X"]},
        ])

        assert "E_STALE_ANCHOR" in result
        assert f.read_text(encoding="utf-8").splitlines() == lines

    def test_writes_lf_only(self, tmp_path):
        lines = ["a", "b"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 1), "lines": ["X"]},
        ])

        assert b"\r\n" not in f.read_bytes()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -v`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'edits'`

- [ ] **Step 3: Write minimal implementation**

Replace the entire contents of `tools/edit/_edit.py`:

```python
"""Hash-anchored edit tool.

Edits target LINE#HASH anchors from `read` or `grep`. Validation is stateless:
the anchor table is rebuilt from disk on every call, so a changed file produces
a loud E_STALE_ANCHOR rather than a silent wrong-line edit.
"""
from dataclasses import dataclass
from pathlib import Path

from agent.base_tool import BaseTool
from tools import _hashline as H
from tools._path_guard import validate_path

_DOC_EXTS = {".pdf", ".docx", ".xlsx", ".pptx"}


@dataclass
class _Resolved:
    """An edit reduced to a splice against the pre-edit line list."""

    start: int          # 0-based, inclusive
    end: int            # 0-based, exclusive
    lines: list[str]
    index: int          # position in the caller's edits list, for messages


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _resolve_replace(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    pos = edit.get("pos")
    if not pos:
        raise H.AnchorError("E_INVALID_ANCHOR", f"edit {i}: replace requires 'pos'")
    start = H.resolve_anchor(pos, anchors)
    end_anchor = edit.get("end")
    end = H.resolve_anchor(end_anchor, anchors) if end_anchor else start
    if end < start:
        raise H.AnchorError("E_INVALID_ANCHOR", f"edit {i}: 'end' precedes 'pos'")
    return _Resolved(start, end + 1, list(edit.get("lines", [])), i)


_RESOLVERS = {"replace": _resolve_replace}


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Edit a file using hash anchors from `read` or `grep`. Each anchor is a "
        "`LINE#HASH` token (e.g. `18#aB3`) that is re-verified against the file "
        "before the edit is applied, so an edit can never land on the wrong line. "
        "Pass a list of edits; they are applied together against a single "
        "pre-edit snapshot. Returns fresh anchors for the changed region. "
        "Paths are relative to the project root."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit (relative to project root, or absolute)",
            },
            "edits": {
                "type": "array",
                "description": "Edit operations applied against one pre-edit snapshot",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {
                            "type": "string",
                            "enum": ["replace"],
                            "description": "Operation kind",
                        },
                        "pos": {
                            "type": "string",
                            "description": "Anchor of the target line, e.g. '18#aB3'",
                        },
                        "end": {
                            "type": "string",
                            "description": "Optional end anchor for an inclusive range replace",
                        },
                        "lines": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Replacement lines, without any LINE#HASH prefix",
                        },
                    },
                    "required": ["op"],
                },
            },
        },
        "required": ["path", "edits"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(self, path: str, edits: list[dict]) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)

        if not edits:
            return "Error: [E_INVALID_PATCH] 'edits' must contain at least one operation."

        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return f"Error: cannot read {p.name} as UTF-8 text."

        anchors = H.build_anchors(lines)
        try:
            resolved = self._resolve_all(edits, lines, anchors)
        except H.AnchorError as exc:
            return f"Error: [{exc.code}] {exc.message}"

        new_lines = self._apply(lines, resolved)
        p.write_text("\n".join(new_lines), encoding="utf-8", newline="\n")
        return f"Edited {p.name}"

    def _resolve_all(
        self,
        edits: list[dict],
        lines: list[str],
        anchors: list[str],
    ) -> list[_Resolved]:
        resolved: list[_Resolved] = []
        for i, edit in enumerate(edits):
            op = edit.get("op")
            resolver = _RESOLVERS.get(op)
            if resolver is None:
                raise H.AnchorError(
                    "E_INVALID_PATCH",
                    f"edit {i}: unknown op {op!r}; expected one of {sorted(_RESOLVERS)}",
                )
            resolved.append(resolver(edit, i, lines, anchors))
        return resolved

    @staticmethod
    def _apply(lines: list[str], resolved: list[_Resolved]) -> list[str]:
        """Splice bottom-up so unapplied indices stay valid."""
        out = list(lines)
        for e in sorted(resolved, key=lambda r: (r.start, r.index), reverse=True):
            out[e.start:e.end] = e.lines
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add tools/edit/_edit.py tests/test_edit_tool.py
git commit -m "feat: rewrite edit tool around hash anchors with replace op"
```

---

## Task 7: `append` and `prepend`

**Files:**
- Modify: `tools/edit/_edit.py`
- Test: `tests/test_edit_tool.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_edit_tool.py`:

```python
class TestAppendPrepend:
    def test_append_after_position(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "append", "pos": _anchor_for(lines, 1), "lines": ["NEW"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "NEW", "b", "c"]

    def test_append_without_pos_goes_to_eof(self, tmp_path):
        lines = ["a", "b"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[{"op": "append", "lines": ["END"]}])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "b", "END"]

    def test_prepend_before_position(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "prepend", "pos": _anchor_for(lines, 3), "lines": ["NEW"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "b", "NEW", "c"]

    def test_prepend_without_pos_goes_to_bof(self, tmp_path):
        lines = ["a", "b"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[{"op": "prepend", "lines": ["TOP"]}])

        assert f.read_text(encoding="utf-8").splitlines() == ["TOP", "a", "b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -k AppendPrepend -v`
Expected: FAIL — `E_INVALID_PATCH` unknown op `'append'`

- [ ] **Step 3: Write minimal implementation**

In `tools/edit/_edit.py`, add after `_resolve_replace`:

```python
def _resolve_append(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    pos = edit.get("pos")
    at = len(lines) if not pos else H.resolve_anchor(pos, anchors) + 1
    return _Resolved(at, at, list(edit.get("lines", [])), i)


def _resolve_prepend(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    pos = edit.get("pos")
    at = 0 if not pos else H.resolve_anchor(pos, anchors)
    return _Resolved(at, at, list(edit.get("lines", [])), i)
```

Replace the `_RESOLVERS` assignment with:

```python
_RESOLVERS = {
    "replace": _resolve_replace,
    "append": _resolve_append,
    "prepend": _resolve_prepend,
}
```

Update the `op` enum in `_parameters` to `["replace", "append", "prepend"]` and
extend the `pos` description:

```python
                        "pos": {
                            "type": "string",
                            "description": (
                                "Anchor of the target line, e.g. '18#aB3'. For append, "
                                "omit to insert at end of file; for prepend, omit to "
                                "insert at start of file."
                            ),
                        },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add tools/edit/_edit.py tests/test_edit_tool.py
git commit -m "feat: add append and prepend ops to edit tool"
```

---

## Task 8: `replace_text` desugaring

**Files:**
- Modify: `tools/edit/_edit.py`
- Test: `tests/test_edit_tool.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_edit_tool.py`:

```python
class TestReplaceText:
    def test_replaces_unique_substring(self, tmp_path):
        lines = ["alpha", "beta", "gamma"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace_text", "oldText": "beta", "newText": "BETA"},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["alpha", "BETA", "gamma"]

    def test_replaces_across_multiple_lines(self, tmp_path):
        lines = ["a", "b", "c", "d"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace_text", "oldText": "b\nc", "newText": "X"},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "X", "d"]

    def test_missing_text_reports_not_found(self, tmp_path):
        f = _write(tmp_path, "f.txt", ["a", "b"])
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {"op": "replace_text", "oldText": "zzz", "newText": "X"},
        ])

        assert "E_TEXT_NOT_FOUND" in result
        assert f.read_text(encoding="utf-8").splitlines() == ["a", "b"]

    def test_ambiguous_text_reports_ambiguous(self, tmp_path):
        f = _write(tmp_path, "f.txt", ["dup", "dup"])
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {"op": "replace_text", "oldText": "dup", "newText": "X"},
        ])

        assert "E_TEXT_AMBIGUOUS" in result
        assert f.read_text(encoding="utf-8").splitlines() == ["dup", "dup"]

    def test_normalises_crlf_in_supplied_text(self, tmp_path):
        f = _write(tmp_path, "f.txt", ["a", "b", "c"])
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace_text", "oldText": "a\r\nb", "newText": "X"},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["X", "c"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -k ReplaceText -v`
Expected: FAIL — `E_INVALID_PATCH` unknown op `'replace_text'`

- [ ] **Step 3: Write minimal implementation**

In `tools/edit/_edit.py`, add after `_resolve_prepend`:

```python
def _resolve_replace_text(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    """Desugar a substring replacement into an ordinary line-range splice.

    Resolving here means the positional path is the only execution path, so
    ordering and conflict rules apply uniformly to every op.
    """
    old = _norm(edit.get("oldText", ""))
    new = _norm(edit.get("newText", ""))
    if not old:
        raise H.AnchorError("E_INVALID_PATCH", f"edit {i}: replace_text requires 'oldText'")

    content = "\n".join(lines)
    count = content.count(old)
    if count == 0:
        raise H.AnchorError("E_TEXT_NOT_FOUND", f"edit {i}: oldText not found in file")
    if count > 1:
        raise H.AnchorError(
            "E_TEXT_AMBIGUOUS",
            f"edit {i}: oldText found {count} times; use a hash anchor instead",
        )

    offset = content.index(old)
    start = content.count("\n", 0, offset)
    end = content.count("\n", 0, offset + len(old))
    span = "\n".join(lines[start:end + 1])
    return _Resolved(start, end + 1, span.replace(old, new, 1).split("\n"), i)
```

Add `"replace_text": _resolve_replace_text` to `_RESOLVERS`, extend the `op`
enum to `["replace", "append", "prepend", "replace_text"]`, and add the two
parameter descriptions:

```python
                        "oldText": {
                            "type": "string",
                            "description": (
                                "replace_text only: exact unique substring to replace. "
                                "Fallback for when an anchor has gone stale — prefer "
                                "`replace` with a fresh anchor."
                            ),
                        },
                        "newText": {
                            "type": "string",
                            "description": "replace_text only: replacement substring",
                        },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -v`
Expected: PASS, 15 tests

- [ ] **Step 5: Commit**

```bash
git add tools/edit/_edit.py tests/test_edit_tool.py
git commit -m "feat: desugar replace_text into positional splice"
```

---

## Task 9: Batching, ordering, and conflicts

**Files:**
- Modify: `tools/edit/_edit.py`
- Test: `tests/test_edit_tool.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_edit_tool.py`:

```python
class TestBatching:
    def test_two_replaces_in_one_call(self, tmp_path):
        lines = ["a", "b", "c", "d"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 1), "lines": ["A"]},
            {"op": "replace", "pos": _anchor_for(lines, 4), "lines": ["D"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["A", "b", "c", "D"]

    def test_earlier_insert_does_not_shift_later_edit(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "append", "pos": _anchor_for(lines, 1), "lines": ["X", "Y"]},
            {"op": "replace", "pos": _anchor_for(lines, 3), "lines": ["C"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "X", "Y", "b", "C"]

    def test_two_inserts_at_same_position_keep_caller_order(self, tmp_path):
        lines = ["a", "b"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "append", "pos": _anchor_for(lines, 1), "lines": ["FIRST"]},
            {"op": "append", "pos": _anchor_for(lines, 1), "lines": ["SECOND"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "FIRST", "SECOND", "b"]

    def test_overlapping_edits_report_conflict(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {
                "op": "replace",
                "pos": _anchor_for(lines, 1),
                "end": _anchor_for(lines, 2),
                "lines": ["X"],
            },
            {"op": "replace", "pos": _anchor_for(lines, 2), "lines": ["Y"]},
        ])

        assert "E_CONFLICT" in result
        assert f.read_text(encoding="utf-8").splitlines() == lines

    def test_one_bad_anchor_aborts_the_whole_batch(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 1), "lines": ["A"]},
            {"op": "replace", "pos": "2#zzz", "lines": ["B"]},
        ])

        assert "E_STALE_ANCHOR" in result
        assert f.read_text(encoding="utf-8").splitlines() == lines
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -k Batching -v`
Expected: FAIL — `test_overlapping_edits_report_conflict` fails; no conflict detection exists

- [ ] **Step 3: Write minimal implementation**

In `tools/edit/_edit.py`, add a module-level helper after `_resolve_replace_text`:

```python
def _check_conflicts(resolved: list[_Resolved]) -> None:
    ordered = sorted(resolved, key=lambda r: (r.start, r.end))
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.start < prev.end:
            raise H.AnchorError(
                "E_CONFLICT",
                f"edits {prev.index} and {nxt.index} target overlapping line ranges",
            )
```

In `run()`, call it inside the existing `try` block, immediately after `_resolve_all`:

```python
        try:
            resolved = self._resolve_all(edits, lines, anchors)
            _check_conflicts(resolved)
        except H.AnchorError as exc:
            return f"Error: [{exc.code}] {exc.message}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -v`
Expected: PASS, 20 tests

- [ ] **Step 5: Commit**

```bash
git add tools/edit/_edit.py tests/test_edit_tool.py
git commit -m "feat: add batch conflict detection to edit tool"
```

---

## Task 10: Anchors response and noop classification

**Files:**
- Modify: `tools/edit/_edit.py`
- Test: `tests/test_edit_tool.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_edit_tool.py`:

```python
class TestEditResponse:
    def test_returns_fresh_anchors_for_changed_region(self, tmp_path):
        lines = [f"L{i}" for i in range(1, 11)]
        _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 5), "lines": ["FIVE"]},
        ])

        assert result.startswith("--- Anchors 3-7 ---")
        assert ":FIVE" in result

    def test_returned_anchors_are_usable_for_a_follow_up_edit(self, tmp_path):
        lines = [f"L{i}" for i in range(1, 11)]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        first = tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 5), "lines": ["FIVE"]},
        ])
        anchor_line = [ln for ln in first.splitlines() if ":FIVE" in ln][0]
        anchor = anchor_line.split(":", 1)[0].strip()

        second = tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": anchor, "lines": ["CINCO"]},
        ])

        assert "E_STALE_ANCHOR" not in second
        assert f.read_text(encoding="utf-8").splitlines()[4] == "CINCO"

    def test_large_edit_omits_anchors(self, tmp_path):
        lines = [f"L{i}" for i in range(1, 51)]
        _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[{
            "op": "replace",
            "pos": _anchor_for(lines, 1),
            "end": _anchor_for(lines, 40),
            "lines": [f"N{i}" for i in range(1, 41)],
        }])

        assert result == H.ANCHORS_OMITTED_TEXT

    def test_identical_content_reports_noop(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 2), "lines": ["b"]},
        ])

        assert "noop" in result.lower()
        assert f.read_text(encoding="utf-8").splitlines() == lines
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -k EditResponse -v`
Expected: FAIL — response is still `"Edited f.txt"`

- [ ] **Step 3: Write minimal implementation**

In `tools/edit/_edit.py`, add two module-level helpers after `_check_conflicts`:

```python
def _changed_span(resolved: list[_Resolved]) -> tuple[int | None, int | None]:
    """First and last changed line in POST-edit 1-indexed coordinates."""
    offset = 0
    first: int | None = None
    last: int | None = None
    for e in sorted(resolved, key=lambda r: (r.start, r.index)):
        post_start = e.start + offset
        candidate_last = post_start + len(e.lines) if e.lines else post_start
        first = post_start + 1 if first is None else min(first, post_start + 1)
        last = candidate_last if last is None else max(last, candidate_last)
        offset += len(e.lines) - (e.end - e.start)
    return first, last


def _render_anchors(new_lines: list[str], resolved: list[_Resolved]) -> str:
    first, last = _changed_span(resolved)
    span = H.compute_affected_range(first, last, len(new_lines))
    if span is None:
        return H.ANCHORS_OMITTED_TEXT
    start, end = span
    anchors = H.build_anchors(new_lines)
    block = (
        f"--- Anchors {start}-{end} ---\n"
        + H.format_region(new_lines, anchors, start, end)
    )
    if len(block.encode("utf-8")) > H.ANCHOR_TEXT_BUDGET_BYTES:
        return H.ANCHORS_OMITTED_TEXT
    return block
```

Replace the final three lines of `run()` with:

```python
        new_lines = self._apply(lines, resolved)
        if new_lines == lines:
            return f"No changes made to {p.name}\nClassification: noop"

        p.write_text("\n".join(new_lines), encoding="utf-8", newline="\n")
        return _render_anchors(new_lines, resolved)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -v`
Expected: PASS, 24 tests

- [ ] **Step 5: Commit**

```bash
git add tools/edit/_edit.py tests/test_edit_tool.py
git commit -m "feat: return fresh anchor block from edit, classify noops"
```

---

## Task 11: Document guard and display-prefix guard

**Files:**
- Modify: `tools/edit/_edit.py`
- Test: `tests/test_edit_tool.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_edit_tool.py`:

```python
class TestGuards:
    def test_editing_a_pdf_points_at_the_cache_path(self, tmp_path):
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf", edits=[
            {"op": "append", "lines": ["x"]},
        ])

        assert "cannot edit .pdf directly" in result
        assert "doc_convert" in result

    def test_docx_is_also_guarded(self, tmp_path):
        f = tmp_path / "notes.docx"
        f.write_bytes(b"PK fake")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.docx", edits=[
            {"op": "append", "lines": ["x"]},
        ])

        assert "cannot edit .docx directly" in result

    def test_anchor_prefix_in_content_is_rejected(self, tmp_path):
        lines = ["a", "b"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 1), "lines": ["1#aB3:a"]},
        ])

        assert "E_INVALID_PATCH" in result
        assert f.read_text(encoding="utf-8").splitlines() == lines

    def test_yaml_frontmatter_is_allowed_as_content(self, tmp_path):
        lines = ["a", "b"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "prepend", "lines": ["---", "name: x", "---"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines()[0] == "---"

    def test_empty_edits_list_is_rejected(self, tmp_path):
        _write(tmp_path, "f.txt", ["a"])
        tool = _make_tool(tmp_path)

        assert "E_INVALID_PATCH" in tool.run(path="f.txt", edits=[])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -k Guards -v`
Expected: FAIL — PDF edit returns a UTF-8 error rather than the cache-path message

- [ ] **Step 3: Write minimal implementation**

In `tools/edit/_edit.py`, add the import:

```python
from tools.read._doc_service import cache_path_for
```

Add a module-level helper after `_norm`:

```python
def _doc_guard(p: Path) -> str | None:
    """Redirect document edits to the converted-markdown cache entry."""
    ext = p.suffix.lower()
    if ext not in _DOC_EXTS:
        return None
    try:
        target = cache_path_for(p, p.parent)
        hint = f".dagi/hash_cache/doc_convert/{target.name}"
    except OSError:
        hint = ".dagi/hash_cache/doc_convert/<sha256>.md"
    return (
        f"Error: cannot edit {ext} directly — edit the converted markdown at "
        f"{hint} (read the document first to have it converted)."
    )
```

In `run()`, insert the guard immediately after `validate_path`, before the
empty-`edits` check:

```python
        doc_error = _doc_guard(p)
        if doc_error:
            return doc_error
```

Add the display-prefix check inside `_resolve_all`, before dispatching:

```python
        for i, edit in enumerate(edits):
            offending = H.contains_display_prefix(edit.get("lines") or [])
            if offending:
                raise H.AnchorError(
                    "E_INVALID_PATCH",
                    f"edit {i}: content line looks like tool display output "
                    f"({offending!r}); supply file content without LINE#HASH prefixes",
                )
            op = edit.get("op")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_edit_tool.py -v`
Expected: PASS, 29 tests

- [ ] **Step 5: Commit**

```bash
git add tools/edit/_edit.py tests/test_edit_tool.py
git commit -m "feat: guard document edits and reject display-prefixed content"
```

---

## Task 12: `grep` emits anchors

**Files:**
- Modify: `tools/grep/_grep.py`
- Test: `tests/test_grep_tool.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_grep_tool.py`:

```python
from tools import _hashline as H
from tools.grep import GrepTool


def _make_tool(tmp_path):
    return GrepTool(cwd=tmp_path, allowed_roots=[tmp_path])


class TestGrepAnchors:
    def test_match_carries_an_anchor(self, tmp_path):
        lines = ["alpha", "needle", "gamma"]
        (tmp_path / "f.txt").write_text("\n".join(lines), encoding="utf-8", newline="\n")
        tool = _make_tool(tmp_path)

        result = tool.run(pattern="needle")

        anchors = H.build_anchors(lines)
        assert f"2#{anchors[1]}:needle" in result

    def test_anchor_matches_the_read_tool_anchor(self, tmp_path):
        from tools.read import ReadTool

        lines = ["}", "}", "needle", "}"]
        (tmp_path / "f.txt").write_text("\n".join(lines), encoding="utf-8", newline="\n")

        grep_out = _make_tool(tmp_path).run(pattern="needle")
        read_out = ReadTool(cwd=tmp_path, allowed_roots=[tmp_path]).run(path="f.txt")

        grep_anchor = [ln for ln in grep_out.splitlines() if "needle" in ln][0].split(":")[1]
        read_anchor = [ln for ln in read_out.splitlines() if "needle" in ln][0].split(":")[0].strip()
        assert grep_anchor == read_anchor

    def test_no_matches_message_preserved(self, tmp_path):
        (tmp_path / "f.txt").write_text("alpha", encoding="utf-8", newline="\n")
        tool = _make_tool(tmp_path)

        assert tool.run(pattern="zzzz") == "[no matches]"

    def test_path_with_colon_is_not_mangled(self, tmp_path):
        sub = tmp_path / "a:b" if not _is_windows() else tmp_path / "ab"
        sub.mkdir()
        (sub / "f.txt").write_text("needle", encoding="utf-8", newline="\n")
        tool = _make_tool(tmp_path)

        result = tool.run(pattern="needle")

        assert "needle" in result
        assert "#" in result


def _is_windows():
    import sys
    return sys.platform.startswith("win")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_grep_tool.py -v`
Expected: FAIL — output is `f.txt:2: needle`, no `#` anchor

- [ ] **Step 3: Write minimal implementation**

Replace `tools/grep/_grep.py` lines 1-11 imports and the `run`/`_search_one`
methods. Add imports:

```python
import json
import re
import subprocess
from pathlib import Path

from agent.base_tool import BaseTool
from tools import _hashline as H
from tools._path_guard import validate_path
```

Update the class `description`:

```python
    description = (
        "Search for a pattern in files using regex or literal match. "
        "Returns matches as `path:LINE#HASH:content`, where LINE#HASH is a "
        "verified anchor that can be passed straight to `edit` without reading "
        "the file first. A match rendered as `path:LINE: content` (no #) means "
        "the file could not be decoded as UTF-8 — read it before editing. "
        "Paths are relative to the project root. Uses ripgrep (rg) if available. "
        "When no path is given, searches across all configured search roots."
    )
```

Replace `run`'s aggregation body (lines 51-61) with:

```python
        matches: list[tuple[Path, int, str]] = []
        for search_path in search_paths:
            matches.extend(self._search_one(pattern, search_path, glob, literal))
            if len(matches) >= _MAX_RESULTS:
                break

        truncated = len(matches) > _MAX_RESULTS
        rendered = self._render(matches[:_MAX_RESULTS])
        if truncated:
            rendered.append(f"[truncated — showing first {_MAX_RESULTS} results]")
        return "\n".join(rendered) if rendered else "[no matches]"

    def _render(self, matches: list[tuple[Path, int, str]]) -> list[str]:
        """Group by file so each file is read and hashed exactly once."""
        by_file: dict[Path, list[tuple[int, str]]] = {}
        for fpath, lineno, content in matches:
            by_file.setdefault(fpath, []).append((lineno, content))

        out: list[str] = []
        for fpath, hits in by_file.items():
            anchors = _anchors_for(fpath)
            rel = fpath.relative_to(self.cwd) if fpath.is_relative_to(self.cwd) else fpath
            for lineno, content in hits:
                if anchors is not None and 1 <= lineno <= len(anchors):
                    out.append(f"{rel}:{lineno}#{anchors[lineno - 1]}:{content}")
                else:
                    out.append(f"{rel}:{lineno}: {content}")
        return out
```

Change `_search_one` to return structured tuples. Replace its ripgrep branch with:

```python
    def _search_one(
        self,
        pattern: str,
        search_path: Path,
        glob: str | None,
        literal: bool,
    ) -> list[tuple[Path, int, str]]:
        # ── Try ripgrep first ─────────────────────────────────────────────
        # --json avoids parsing `path:line:content`, which is ambiguous on
        # Windows where absolute paths contain a drive-letter colon.
        try:
            cmd = ["rg", "--json"]
            if literal:
                cmd.append("--fixed-strings")
            if glob:
                cmd += ["--glob", glob]
            cmd += [pattern, str(search_path)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode in (0, 1):
                return _parse_rg_json(result.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # rg not available, fall back to Python
```

Replace the Python fallback's result accumulation (lines 108-118) with:

```python
        results: list[tuple[Path, int, str]] = []
        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    results.append((fpath, lineno, line))
        return results
```

Add two module-level helpers at the end of the file:

```python
def _parse_rg_json(stdout: str) -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for raw in stdout.splitlines():
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if obj.get("type") != "match":
            continue
        data = obj["data"]
        text = data.get("path", {}).get("text")
        if text is None:
            continue
        out.append((Path(text), data["line_number"], data["lines"]["text"].rstrip("\n")))
    return out


def _anchors_for(fpath: Path) -> list[str] | None:
    """Anchors for a file, or None if it is not strictly UTF-8 decodable.

    Anchors must only ever come from a strict UTF-8 read: hashing lossily
    decoded text would produce anchors that can never match edit's table.
    """
    try:
        return H.build_anchors(fpath.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_grep_tool.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add tools/grep/_grep.py tests/test_grep_tool.py
git commit -m "feat: emit hash anchors from grep via structured rg --json output"
```

---

## Task 13: Property tests

**Files:**
- Create: `tests/test_hashline_properties.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_hashline_properties.py`:

```python
"""Invariants the hashline design depends on.

These guard the three properties that make anchors safe: uniqueness within a
file, agreement across tools, and order-independence of batched edits.
"""
import random
from pathlib import Path

from tools import _hashline as H
from tools.edit import EditTool

_REPO = Path(__file__).resolve().parent.parent


class TestUniqueness:
    def test_anchors_unique_across_repo_source_files(self):
        sources = sorted((_REPO / "tools").rglob("*.py"))
        assert sources, "expected to find repo source files"
        for path in sources:
            lines = path.read_text(encoding="utf-8").splitlines()
            anchors = H.build_anchors(lines)
            assert len(set(anchors)) == len(anchors), f"duplicate anchor in {path}"

    def test_anchors_unique_on_pathological_input(self):
        lines = ["}"] * 500 + [""] * 500
        anchors = H.build_anchors(lines)
        assert len(set(anchors)) == 1000


class TestCrossToolAgreement:
    def test_read_and_grep_agree_with_edit(self, tmp_path):
        from tools.grep import GrepTool
        from tools.read import ReadTool

        lines = ["import os", "import os", "needle", "import os"]
        (tmp_path / "f.py").write_text("\n".join(lines), encoding="utf-8", newline="\n")

        read_line = [
            ln for ln in ReadTool(cwd=tmp_path, allowed_roots=[tmp_path])
            .run(path="f.py").splitlines() if "needle" in ln
        ][0]
        grep_line = [
            ln for ln in GrepTool(cwd=tmp_path, allowed_roots=[tmp_path])
            .run(pattern="needle").splitlines() if "needle" in ln
        ][0]

        read_anchor = read_line.split(":", 1)[0].strip()
        grep_anchor = grep_line.split(":", 2)[1].strip()

        assert read_anchor == grep_anchor

        result = EditTool(cwd=tmp_path, allowed_roots=[tmp_path]).run(
            path="f.py",
            edits=[{"op": "replace", "pos": read_anchor, "lines": ["found"]}],
        )
        assert "E_STALE_ANCHOR" not in result


class TestBottomUpEquivalence:
    def test_batch_matches_sequential_descending_application(self, tmp_path):
        rng = random.Random(1234)
        for trial in range(20):
            lines = [f"L{i}" for i in range(1, 31)]
            targets = sorted(rng.sample(range(1, 31), 4))
            anchors = H.build_anchors(lines)
            edits = [
                {
                    "op": "replace",
                    "pos": f"{n}#{anchors[n - 1]}",
                    "lines": [f"X{n}a", f"X{n}b"],
                }
                for n in targets
            ]

            batched = tmp_path / f"batch{trial}.txt"
            batched.write_text("\n".join(lines), encoding="utf-8", newline="\n")
            EditTool(cwd=tmp_path, allowed_roots=[tmp_path]).run(
                path=batched.name, edits=edits
            )

            manual = list(lines)
            for n in reversed(targets):
                manual[n - 1:n] = [f"X{n}a", f"X{n}b"]

            assert batched.read_text(encoding="utf-8").splitlines() == manual
```

- [ ] **Step 2: Run tests**

Run: `conda run -n dagi python -m pytest tests/test_hashline_properties.py -v`
Expected: PASS, 4 tests

If `test_anchors_unique_across_repo_source_files` fails, the collision-retry
loop in `build_anchors` is wrong — fix `tools/_hashline.py`, not the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_hashline_properties.py
git commit -m "test: add hashline uniqueness, cross-tool, and ordering invariants"
```

---

## Task 14: Prose migration and full-suite verification

**Files:**
- Modify: `AGENTS.md:199`, `README.md`, `TODO.md`
- Modify: `projects/project_management_system/.dagi/skills/pms-ingest/SKILL.md:254`

- [ ] **Step 1: Replace the read-format note in AGENTS.md**

Replace the bullet at `AGENTS.md:199` with:

```markdown
- **`read`/`grep`/`edit` anchor format (hashline, 2026-07-26)**: `read` prefixes every line with `LINE#HASH:` (e.g. `18#aB3:def f():`); `grep` returns `path:LINE#HASH:content`. The hash is 3 base64url chars derived from `blake2b(prev\0curr\0next)`, keeping 6 bits per char (262,144 buckets), with collisions inside a file resolved by appending `:R{retry}` to the hash input until unique — so every line has a globally unique anchor and repeated lines (`}`, duplicate imports) are individually addressable. `tools/_hashline.py` is the single source of truth; no tool hashes independently, which is what makes a grep anchor valid in `edit` without an intervening read. The prefix is not part of file content and must be stripped before use as content. `edit` takes `{path, edits: [...]}` with ops `replace`/`append`/`prepend`/`replace_text`, resolves every edit against one pre-edit snapshot, rejects overlapping ranges (`E_CONFLICT`), and applies splices bottom-up. Validation is stateless — the anchor table is rebuilt from disk on every call, so a changed file yields `E_STALE_ANCHOR` and a re-read instruction rather than a silent wrong-line edit; there is no snapshot cache and no 3-way merge, which is what makes it safe across the subagent subprocess boundary. Known accepted risk: because retry indices are assigned in scan order, a newly introduced collision can shift the retry index of a colliding line far below it and invalidate an anchor the model still holds — the failure mode is a clean `E_STALE_ANCHOR`, never a wrong edit. On success `edit` returns only a fresh anchor block for the changed region (±2 lines, max 12 lines, 50 KB), degrading to `"Anchors omitted; use read for subsequent edits."` Design: `docs/superpowers/specs/2026-07-26-hashline-read-edit-design.md`.
```

- [ ] **Step 2: Update the pms-ingest troubleshooting line**

Replace `projects/project_management_system/.dagi/skills/pms-ingest/SKILL.md:254` with:

```markdown
- **`edit` reports `E_STALE_ANCHOR`:** The file changed since you read it. Re-read the file to get fresh `LINE#HASH` anchors, then retry. Do not guess an anchor.
```

- [ ] **Step 3: Update README.md and TODO.md**

In `README.md`, update the sentence describing the `edit` tool so it reads:

```markdown
- `edit` — hash-anchored editing: targets `LINE#HASH` anchors from `read`/`grep`, batched, with stale anchors rejected rather than silently relocated
```

In `TODO.md`, add a completed entry under the most recent dated section:

```markdown
- [x] Hash-anchored `read`/`edit`/`grep` (hashline) — replaces substring `oldText` matching; spec `docs/superpowers/specs/2026-07-26-hashline-read-edit-design.md`, plan `docs/superpowers/plans/2026-07-26-hashline-read-edit.md`
```

- [ ] **Step 4: Run the full suite**

Run: `conda run -n dagi python -m pytest tests/ -q`
Expected: PASS. Baseline before this work was 463 passed; expect roughly 463 + 47 new tests, with no failures.

If `tests/test_scope_tools.py` fails, it is asserting tool *types* only and should not need changes — investigate rather than editing the assertions.

- [ ] **Step 5: Manual smoke test**

```bash
conda run -n dagi python -c "
from pathlib import Path
from tools.read import ReadTool
from tools.edit import EditTool
p = Path('.')
print(ReadTool(cwd=p, allowed_roots=[p]).run(path='tools/_hashline.py', offset=1, limit=5))
"
```
Expected: five lines prefixed `1#…:` through `5#…:`. Confirm visually that the
anchors are three characters and the content is unmangled.

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md README.md TODO.md projects/project_management_system/.dagi/skills/pms-ingest/SKILL.md
git commit -m "docs: document hashline anchor format and retire oldText guidance"
```

---

## Self-Review Notes

**Spec coverage:** Decision 1 (hard replace) → Tasks 4, 6-11. Decision 2 (stateless) → Task 6, no snapshot module anywhere in the plan. Decision 3 (anchors response) → Task 10. Decision 4 (3-char base64url + perfect hashing) → Task 1. Decision 5 (grep anchors) → Task 12. Decision 6 (documents) → Tasks 5, 11. Decision 7 (`replace_text` desugared) → Task 8. Testing section → Tasks 1-13. Migration section → Task 14. Risks → covered by Task 13 property tests and Task 14 step 5.

**Type consistency:** `H.build_anchors`, `H.format_region`, `H.compute_affected_range`, `H.parse_anchor`, `H.resolve_anchor`, `H.contains_display_prefix`, `H.AnchorError`, `H.ANCHORS_OMITTED_TEXT`, `H.ANCHOR_TEXT_BUDGET_BYTES` are defined in Tasks 1-3 and used with identical names and signatures thereafter. `_Resolved(start, end, lines, index)` is defined in Task 6 and constructed identically in Tasks 7-8. `cache_path_for(path, project_path)` is defined in Task 5 and reused in Task 11.

**Deviation flagged during planning:** Task 12 replaces `rg`'s plain output with `rg --json`. The existing code returns `rg` stdout verbatim and never parses it; anchoring requires parsing, and `path:line:content` is ambiguous on Windows because absolute paths contain a drive-letter colon. `--json` removes the ambiguity rather than papering over it.
