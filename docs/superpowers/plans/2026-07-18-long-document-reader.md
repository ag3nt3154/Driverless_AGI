# Long Document Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `ReadTool` output exceeds the token budget, automatically spawn a `document-reader` subagent that produces a sectioned summary digest (with line ranges, token estimates, key excerpts) instead of dumb truncation.

**Architecture:** `ReadTool.run()` gains a size check after reading full text. Over-budget documents go through a cache-check → subagent-spawn → read-handoff pipeline. The subagent is a new entry under `.dagi/subagents/document-reader/` using the existing piped-subprocess infrastructure (`_subagent_runner.py`). Summaries are cached in `.dagi/hash_cache/document_summary/` keyed by content SHA-256.

**Tech Stack:** Python 3.14, pytest, existing DAGI subagent infrastructure (`tools/_subagent_runner.py`, `tools/spawn_subagent.py`, `tools/subagent_main.py`), `tools/_hash_cache.py`.

**Spec:** `docs/superpowers/specs/2026-07-18-long-document-reader-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `tools/_document_reader.py` | Create | Orchestration: `summarize_document()` — checks summary cache, spawns subagent, reads handoff, returns digest. Called by `ReadTool.run()`. |
| `tools/read.py` | Modify | Add `reserve_tokens` and `project_path` constructor params. After reading full text, check size → delegate to `_document_reader.summarize_document()` if over budget. |
| `agent/tools.py` | Modify | Pass `reserve_tokens` and `project_path` when constructing `ReadTool` (both in `build_registry` and `_tools_from_list`). |
| `.dagi/subagents/document-reader/subagent_config.yaml` | Create | Subagent config: `model_tier: worker`, `tools: [read, grep, write]`. |
| `.dagi/subagents/document-reader/prompt.md` | Create | System prompt for the document reader subagent. |
| `tests/test_document_reader.py` | Create | Tests for `_document_reader.py` (cache hit/miss, fallback on failure, output format). |
| `tests/test_read_tool.py` | Modify | Add tests for the auto-summarization trigger in `ReadTool.run()`. |

---

### Task 1: Create the document-reader subagent config and prompt

**Files:**
- Create: `.dagi/subagents/document-reader/subagent_config.yaml`
- Create: `.dagi/subagents/document-reader/prompt.md`

- [ ] **Step 1: Create `subagent_config.yaml`**

```yaml
model_tier: worker
description: >-
  Read a long document in chunks and produce a sectioned summary digest
  with line ranges, token estimates, and key excerpts. Writes the digest
  to a cache file; the parent reads it back as the tool result.
tools:
  - read
  - grep
  - write
parameters:
  type: object
  properties:
    task:
      type: string
      description: >-
        Instructions including the cached document path, output path,
        and the document filename for the header.
  required:
    - task
```

- [ ] **Step 2: Create `prompt.md`**

```markdown
# Document Reader Subagent

You are a document reader. Your job is to read a long document in chunks and produce a structured summary digest.

## Process

1. **Read the document in chunks** using `read(path, offset, limit)` with ~2000 lines per chunk.
2. **For each chunk**, produce:
   - A section heading (from markdown headings, page markers, or inferred from content)
   - A summary written in context of everything you've read so far
   - Key excerpts: tables, formulas, definitions, critical quotes — with exact line numbers
   - The line range (start-end)
   - Estimated token count for the section (~chars/4)
3. **Maintain an accumulative summary** — each new section's summary is written in light of all prior sections, preserving cross-references and narrative flow.
4. **After reading all chunks**, perform a verification pass:
   - Review your summary for specific claims (numbers, formulas, names, percentages, table values)
   - Use `grep` and targeted `read` calls to verify the most critical details against the source text
   - Correct any inaccuracies and strengthen key excerpts with accurate line references
5. **Write the final digest** to the output path provided in your task using `write`.

## Output Format

Write the digest in this exact format:

```
[Document: <filename> | <N> pages/sections | full text cached: <source_path>]

## <Section Heading> (lines <start>-<end>, ~<T> tokens)
**Summary:** <summary text>
**Key excerpts:**
- L<N>: "<verbatim quote>"
- L<N>-<M>: <description of table/formula/figure>

## <Next Section> (lines <start>-<end>, ~<T> tokens)
...

---
Full text: <source_path>
Use read(path, offset, limit) for verbatim content from any section.
```

## Guidelines

- Be thorough but concise — the parent LLM uses this digest to decide what to drill into
- Preserve important numbers, names, dates, and technical terms exactly
- For tables, reproduce small ones verbatim; for large ones, describe structure and key values
- Note `[Figure N]` or `[Table N]` placeholders when you encounter them
- Section boundaries: prefer markdown headings (`#`, `##`) and `<!-- Page N -->` markers; fall back to ~2000-line windows for unstructured text
- Token estimate: count characters in the chunk and divide by 4
```

- [ ] **Step 3: Verify the subagent is discoverable**

Run: `conda run -n dagi python -c "from pathlib import Path; p = Path('.dagi/subagents/document-reader/subagent_config.yaml'); print('exists:', p.exists()); import yaml; print(yaml.safe_load(p.read_text()))"`

Expected: `exists: True` and the parsed YAML dict.

- [ ] **Step 4: Commit**

```bash
git add .dagi/subagents/document-reader/subagent_config.yaml .dagi/subagents/document-reader/prompt.md
git commit -m "feat: add document-reader subagent config and prompt"
```

---

### Task 2: Create `tools/_document_reader.py` — orchestration module

**Files:**
- Create: `tools/_document_reader.py`
- Create: `tests/test_document_reader.py`

- [ ] **Step 1: Write the failing test for cache hit path**

```python
# tests/test_document_reader.py
from pathlib import Path
from unittest.mock import patch

from tools._document_reader import summarize_document

_CHARS_PER_TOKEN = 4


class TestSummarizeDocumentCacheHit:
    def test_returns_cached_summary_when_exists(self, tmp_path):
        full_text = "x" * 200_000  # ~50k tokens, well over any budget
        # Pre-populate the cache
        import hashlib
        content_hash = hashlib.sha256(full_text.encode()).hexdigest()
        cache_dir = tmp_path / ".dagi" / "hash_cache" / "document_summary"
        cache_dir.mkdir(parents=True)
        cached_summary = "## Introduction (lines 1-100, ~500 tokens)\n**Summary:** test"
        (cache_dir / f"{content_hash}_summary.md").write_text(
            cached_summary, encoding="utf-8"
        )

        result = summarize_document(
            full_text=full_text,
            source_path=tmp_path / "big.txt",
            filename="big.txt",
            project_path=tmp_path,
        )

        assert result == cached_summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_document_reader.py::TestSummarizeDocumentCacheHit::test_returns_cached_summary_when_exists -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'tools._document_reader'`

- [ ] **Step 3: Write the failing test for cache miss (subagent spawn)**

```python
class TestSummarizeDocumentCacheMiss:
    def test_spawns_subagent_and_returns_written_summary(self, tmp_path):
        full_text = "x" * 200_000
        import hashlib
        content_hash = hashlib.sha256(full_text.encode()).hexdigest()
        expected_summary_path = (
            tmp_path / ".dagi" / "hash_cache" / "document_summary"
            / f"{content_hash}_summary.md"
        )

        fake_summary = "## Section 1 (lines 1-50, ~200 tokens)\n**Summary:** fake"

        def fake_run_subagent(
            subagent_type, task, project_path, handoff_path, timeout, on_event
        ):
            # Simulate what the subagent does: write the summary file
            expected_summary_path.parent.mkdir(parents=True, exist_ok=True)
            expected_summary_path.write_text(fake_summary, encoding="utf-8")
            # Write handoff
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text("done", encoding="utf-8")
            return {"status": "ok", "handoff": str(handoff_path)}

        with patch(
            "tools._document_reader.run_subagent", side_effect=fake_run_subagent
        ):
            result = summarize_document(
                full_text=full_text,
                source_path=tmp_path / "big.txt",
                filename="big.txt",
                project_path=tmp_path,
            )

        assert result == fake_summary
```

- [ ] **Step 4: Write the failing test for subagent failure fallback**

```python
class TestSummarizeDocumentFallback:
    def test_returns_none_when_subagent_fails(self, tmp_path):
        full_text = "x" * 200_000

        def fake_run_subagent(**kwargs):
            return {"status": "error", "message": "subagent crashed"}

        with patch(
            "tools._document_reader.run_subagent", side_effect=fake_run_subagent
        ):
            result = summarize_document(
                full_text=full_text,
                source_path=tmp_path / "big.txt",
                filename="big.txt",
                project_path=tmp_path,
            )

        assert result is None
```

- [ ] **Step 5: Implement `tools/_document_reader.py`**

```python
"""tools/_document_reader.py — Orchestrate document-reader subagent for long documents."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from tools._subagent_runner import run_subagent

_SUMMARY_SUBDIR = "document_summary"
_HASH_CACHE_DIR = ".dagi/hash_cache"


def _summary_cache_path(content_hash: str, project_path: Path) -> Path:
    return (
        project_path / _HASH_CACHE_DIR / _SUMMARY_SUBDIR
        / f"{content_hash}_summary.md"
    )


def summarize_document(
    full_text: str,
    source_path: Path,
    filename: str,
    project_path: Path,
    on_event: Callable[[str], None] | None = None,
    timeout: float = 1800.0,
) -> str | None:
    """Spawn a document-reader subagent to produce a sectioned summary.

    Returns the summary string on success, or None on failure (caller
    should fall back to truncation).
    """
    content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    summary_path = _summary_cache_path(content_hash, project_path)

    # Cache hit — return immediately
    if summary_path.exists():
        return summary_path.read_text(encoding="utf-8")

    # Cache miss — save full text, spawn subagent
    full_text_dir = project_path / _HASH_CACHE_DIR / "tool_output"
    full_text_dir.mkdir(parents=True, exist_ok=True)
    full_text_path = full_text_dir / f"{content_hash}.txt"
    if not full_text_path.exists():
        full_text_path.write_text(full_text, encoding="utf-8", newline="\n")

    summary_path.parent.mkdir(parents=True, exist_ok=True)

    task = (
        f"Read the document at: {full_text_path}\n"
        f"Filename: {filename}\n"
        f"Write the sectioned summary digest to: {summary_path}\n"
        f"Source path (for the header): {source_path}\n"
    )

    handoff_dir = project_path / ".dagi" / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = handoff_dir / f"document_reader_{content_hash[:12]}.md"

    result = run_subagent(
        subagent_type="document-reader",
        task=task,
        project_path=project_path,
        handoff_path=handoff_path,
        timeout=timeout,
        on_event=on_event,
    )

    if result["status"] == "ok" and summary_path.exists():
        return summary_path.read_text(encoding="utf-8")

    return None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_document_reader.py -v`

Expected: 3 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/_document_reader.py tests/test_document_reader.py
git commit -m "feat: add document reader orchestration module with cache + subagent spawn"
```

---

### Task 3: Wire `ReadTool` to auto-summarize large documents

**Files:**
- Modify: `tools/read.py`
- Modify: `agent/tools.py:77` (build_registry ReadTool construction)
- Modify: `agent/tools.py:77` (_tools_from_list ReadTool construction)
- Modify: `tests/test_read_tool.py`

- [ ] **Step 1: Write the failing test — large text triggers summarization**

Add to `tests/test_read_tool.py`:

```python
from unittest.mock import patch


class TestAutoSummarization:
    def test_large_file_triggers_summarization(self, tmp_path):
        content = "line\n" * 100_000  # ~500k chars → ~125k tokens
        f = tmp_path / "huge.txt"
        f.write_text(content, encoding="utf-8")
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=16_384,
            project_path=tmp_path,
        )

        fake_summary = "## Section 1 (lines 1-2000, ~2500 tokens)\n**Summary:** lots of lines"

        with patch(
            "tools.read.summarize_document", return_value=fake_summary
        ) as mock_summarize:
            result = tool.run(path="huge.txt")

        assert result == fake_summary
        mock_summarize.assert_called_once()

    def test_small_file_does_not_trigger_summarization(self, tmp_path):
        content = "short file\nonly two lines\n"
        f = tmp_path / "small.txt"
        f.write_text(content, encoding="utf-8")
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=16_384,
            project_path=tmp_path,
        )

        with patch(
            "tools.read.summarize_document"
        ) as mock_summarize:
            result = tool.run(path="small.txt")

        mock_summarize.assert_not_called()
        assert "short file" in result

    def test_summarization_failure_falls_back_to_raw_text(self, tmp_path):
        content = "line\n" * 100_000
        f = tmp_path / "huge.txt"
        f.write_text(content, encoding="utf-8")
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=16_384,
            project_path=tmp_path,
        )

        with patch(
            "tools.read.summarize_document", return_value=None
        ):
            result = tool.run(path="huge.txt")

        # Falls back to raw text (which output_filter will later truncate)
        assert "line" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py::TestAutoSummarization -v`

Expected: FAIL — `ReadTool.__init__() got unexpected keyword argument 'reserve_tokens'`

- [ ] **Step 3: Modify `ReadTool.__init__` to accept config params**

In `tools/read.py`, update the constructor:

```python
def __init__(
    self,
    cwd: Path = Path("."),
    allowed_roots: list[Path] | None = None,
    reserve_tokens: int = 0,
    project_path: Path | None = None,
):
    self.cwd = cwd
    self.allowed_roots = allowed_roots
    self._reserve_tokens = reserve_tokens
    self._project_path = project_path
```

- [ ] **Step 4: Add the auto-summarization gate at the end of `ReadTool.run()`**

Replace the final section of `run()` (after `lines` is populated) with:

```python
    start = max(0, offset - 1)
    selected = lines[start : start + limit]
    numbered = "\n".join(
        f"{i:6d}\t{line}" for i, line in enumerate(selected, start + 1)
    )

    raw_result = f"{header}\n{numbered}" if header else numbered

    # Auto-summarization gate: if the full document is over budget and
    # we're reading from the start (not a targeted offset/limit drill-in),
    # spawn the document-reader subagent.
    if (
        self._reserve_tokens > 0
        and self._project_path is not None
        and offset == 1
        and limit == 2000
    ):
        _CHARS_PER_TOKEN = 4
        full_text = "\n".join(f"{i:6d}\t{line}" for i, line in enumerate(lines, 1))
        estimated_tokens = len(full_text) // _CHARS_PER_TOKEN
        if estimated_tokens >= self._reserve_tokens:
            from tools._document_reader import summarize_document
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

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_read_tool.py -v`

Expected: All tests PASS (including existing tests — they don't pass `reserve_tokens` so default to 0, skipping the gate).

- [ ] **Step 6: Update `build_registry` in `agent/tools.py` to pass config to ReadTool**

At line ~259, change:

```python
reg.register(ReadTool(cwd=cwd, allowed_roots=effective_roots))
```

to:

```python
_reserve = config.reserve_tokens if config else 0
_proj = config.project_path if config else None
reg.register(ReadTool(
    cwd=cwd,
    allowed_roots=effective_roots,
    reserve_tokens=_reserve,
    project_path=_proj,
))
```

- [ ] **Step 7: Update `_tools_from_list` in `agent/tools.py` to pass config to ReadTool**

At line ~77, change:

```python
"read":       ReadTool(cwd=cwd, allowed_roots=allowed_roots),
```

to:

```python
"read":       ReadTool(cwd=cwd, allowed_roots=allowed_roots),
```

No change needed here — subagent registries don't pass `reserve_tokens`, so the ReadTool inside the document-reader subagent will have `reserve_tokens=0` and won't trigger recursive summarization. This is the correct behavior.

- [ ] **Step 8: Run the full test suite**

Run: `conda run -n dagi python -m pytest tests/ -v --tb=short`

Expected: All tests PASS.

- [ ] **Step 9: Commit**

```bash
git add tools/read.py agent/tools.py tests/test_read_tool.py
git commit -m "feat: wire ReadTool to auto-summarize documents exceeding token budget"
```

---

### Task 4: Integration test — end-to-end summarization

**Files:**
- Modify: `tests/test_document_reader.py`

- [ ] **Step 1: Write an integration test that verifies the full pipeline**

```python
class TestEndToEnd:
    def test_read_tool_with_large_file_produces_summary_via_subagent(self, tmp_path):
        """Integration test: ReadTool → _document_reader → mock subagent → cached summary."""
        # Create a large file
        lines = [f"Line {i}: content about topic {i % 5}" for i in range(1, 10_001)]
        content = "\n".join(lines)
        f = tmp_path / "large_doc.txt"
        f.write_text(content, encoding="utf-8")

        fake_summary = (
            "[Document: large_doc.txt | 5 sections | "
            f"full text cached: {tmp_path}]\n\n"
            "## Section 1 (lines 1-2000, ~2500 tokens)\n"
            "**Summary:** Content about various topics.\n"
            "**Key excerpts:**\n"
            "- L1: \"Line 1: content about topic 1\"\n"
        )

        def fake_run_subagent(
            subagent_type, task, project_path, handoff_path, timeout, on_event
        ):
            assert subagent_type == "document-reader"
            assert "large_doc.txt" in task
            # Simulate subagent writing the summary
            import hashlib
            full_text_numbered = "\n".join(
                f"{i:6d}\t{line}" for i, line in enumerate(lines, 1)
            )
            h = hashlib.sha256(full_text_numbered.encode("utf-8")).hexdigest()
            summary_dir = project_path / ".dagi" / "hash_cache" / "document_summary"
            summary_dir.mkdir(parents=True, exist_ok=True)
            (summary_dir / f"{h}_summary.md").write_text(
                fake_summary, encoding="utf-8"
            )
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text("done", encoding="utf-8")
            return {"status": "ok", "handoff": str(handoff_path)}

        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=1_000,  # Low budget to trigger summarization
            project_path=tmp_path,
        )

        with patch(
            "tools._document_reader.run_subagent", side_effect=fake_run_subagent
        ):
            result = tool.run(path="large_doc.txt")

        assert "Section 1" in result
        assert "large_doc.txt" in result

    def test_second_read_hits_cache(self, tmp_path):
        """After first summarization, second read returns cached summary without subagent."""
        lines = [f"Line {i}" for i in range(1, 10_001)]
        content = "\n".join(lines)
        f = tmp_path / "large_doc.txt"
        f.write_text(content, encoding="utf-8")

        fake_summary = "## Cached summary"

        # Pre-populate cache
        import hashlib
        full_text_numbered = "\n".join(
            f"{i:6d}\t{line}" for i, line in enumerate(lines, 1)
        )
        h = hashlib.sha256(full_text_numbered.encode("utf-8")).hexdigest()
        summary_dir = tmp_path / ".dagi" / "hash_cache" / "document_summary"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / f"{h}_summary.md").write_text(
            fake_summary, encoding="utf-8"
        )

        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=1_000,
            project_path=tmp_path,
        )

        with patch(
            "tools._document_reader.run_subagent"
        ) as mock_run:
            result = tool.run(path="large_doc.txt")

        mock_run.assert_not_called()
        assert result == fake_summary
```

- [ ] **Step 2: Run integration tests**

Run: `conda run -n dagi python -m pytest tests/test_document_reader.py::TestEndToEnd -v`

Expected: 2 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_document_reader.py
git commit -m "test: add end-to-end integration tests for document reader pipeline"
```

---

### Task 5: Update docs and project context

**Files:**
- Modify: `README.md`
- Modify: `TODO.md`
- Modify: `AGENTS.md` (via update-project-context skill)

- [ ] **Step 1: Update README.md**

Add a bullet under the tools/features section mentioning automatic long-document summarization:

```markdown
- **Long document auto-summarization** — when a `read` result exceeds the token budget,
  a `document-reader` subagent automatically produces a sectioned summary digest
  (with line ranges, token estimates, and key excerpts) instead of truncating.
  Cached by content hash for instant repeat reads.
```

- [ ] **Step 2: Update TODO.md**

Mark the long-document reading item as completed (if listed), or add a completed entry.

- [ ] **Step 3: Run update-project-context skill to update AGENTS.md**

- [ ] **Step 4: Commit**

```bash
git add README.md TODO.md AGENTS.md
git commit -m "docs: document long-document auto-summarization feature"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - [x] Trigger in `ReadTool.run()` — Task 3, Step 4
   - [x] Cache hit path — Task 2, Step 1 + Task 4, Step 1
   - [x] Cache miss / subagent spawn — Task 2, Steps 3-5
   - [x] Fallback on failure — Task 2, Step 4 + Task 3, Step 1
   - [x] Subagent config + prompt — Task 1
   - [x] `document_summary` cache namespace — Task 2, Step 5
   - [x] Config access (`reserve_tokens`, `project_path`) — Task 3, Steps 3+6
   - [x] Token estimates in output format — Task 1, Step 2 (prompt)
   - [x] Verification pass — Task 1, Step 2 (prompt)
   - [x] Per-section line ranges — Task 1, Step 2 (prompt)
   - [x] No recursive summarization in subagent — Task 3, Step 7 (subagent ReadTool has `reserve_tokens=0`)

2. **Placeholder scan:** No TBDs, TODOs, or incomplete steps found.

3. **Type consistency:**
   - `summarize_document()` signature: consistent between `_document_reader.py` and `read.py` import
   - `ReadTool.__init__` params: consistent between `read.py`, `tools.py`, and test files
   - `run_subagent()` call signature: matches `_subagent_runner.py`
   - Cache path construction: consistent `{content_hash}_summary.md` pattern throughout
