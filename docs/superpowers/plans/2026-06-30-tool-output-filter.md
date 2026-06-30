# Tool Output Filter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a filter layer between `registry.dispatch()` and `_messages` that truncates large tool outputs to a safe preview and saves the full output to a temp file, preventing context-window overflow.

**Architecture:** A pure `filter_tool_output()` function in `tools/output_filter.py` returns `(context_result, full_str)`. The call site in `agent/loop.py` is inserted after sentinel handling — `context_result` enters `_messages` and the TUI callback; `full_str` goes to the JSONL tracker.

**Tech Stack:** Python stdlib only (`tempfile`, `os`, `uuid`, `json`, `pathlib`). No new dependencies.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `tools/output_filter.py` | **Create** | Pure filter function — token estimation, threshold check, temp-file write, message assembly |
| `agent/loop.py` | **Modify** | Wire filter at lines 556–568; split `result_str` into `context_result` / `full_str` |
| `tests/test_output_filter.py` | **Create** | Unit tests for all branches of `filter_tool_output` |

---

## Task 1: Create `tools/output_filter.py` with failing tests first

**Files:**
- Create: `tests/test_output_filter.py`
- Create: `tools/output_filter.py`

### Step 1.1 — Write the failing tests

Create `tests/test_output_filter.py`:

```python
"""tests/test_output_filter.py — Unit tests for filter_tool_output()."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from tools.output_filter import filter_tool_output

_RESERVE = 100   # 100 tokens → threshold chars = 400


class TestPassThrough:
    """Results below the token threshold pass through unchanged."""

    def test_short_string_returned_unchanged(self, tmp_path):
        result = "hello world"
        ctx, full = filter_tool_output(result, _RESERVE, tmp_path)
        assert ctx == "hello world"
        assert full == "hello world"

    def test_short_string_no_file_written(self, tmp_path):
        filter_tool_output("short", _RESERVE, tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_short_list_returned_unchanged(self, tmp_path):
        result = [{"type": "text", "text": "hi"}]
        ctx, full = filter_tool_output(result, _RESERVE, tmp_path)
        assert ctx == result          # original list, not serialised
        assert full == "__list__:" + json.dumps(result)

    def test_exactly_at_threshold_passes_through(self, tmp_path):
        # _RESERVE tokens = _RESERVE * 4 chars — boundary is <, so equal passes
        result = "x" * (_RESERVE * 4 - 1)
        ctx, full = filter_tool_output(result, _RESERVE, tmp_path)
        assert ctx == result


class TestFiltering:
    """Results at or above the token threshold are filtered."""

    def _large(self):
        """A string that exceeds _RESERVE tokens."""
        return "y" * (_RESERVE * 4 + 1)

    def test_full_str_is_always_complete(self, tmp_path):
        large = self._large()
        _, full = filter_tool_output(large, _RESERVE, tmp_path)
        assert full == large

    def test_context_result_is_str_when_filtered(self, tmp_path):
        ctx, _ = filter_tool_output(self._large(), _RESERVE, tmp_path)
        assert isinstance(ctx, str)

    def test_context_result_contains_preview(self, tmp_path):
        large = self._large()
        ctx, _ = filter_tool_output(large, _RESERVE, tmp_path)
        preview_chars = (_RESERVE // 2) * 4
        assert large[:preview_chars] in ctx

    def test_context_result_contains_truncation_marker(self, tmp_path):
        ctx, _ = filter_tool_output(self._large(), _RESERVE, tmp_path)
        assert "OUTPUT TRUNCATED" in ctx

    def test_context_result_contains_file_path(self, tmp_path):
        ctx, _ = filter_tool_output(self._large(), _RESERVE, tmp_path)
        assert str(tmp_path) in ctx

    def test_temp_file_written_with_full_content(self, tmp_path):
        large = self._large()
        filter_tool_output(large, _RESERVE, tmp_path)
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == large

    def test_temp_file_has_correct_prefix_and_suffix(self, tmp_path):
        filter_tool_output(self._large(), _RESERVE, tmp_path)
        files = list(tmp_path.iterdir())
        assert files[0].name.startswith("tool_output_")
        assert files[0].name.endswith(".txt")

    def test_large_list_is_filtered(self, tmp_path):
        # Build a list whose serialised form exceeds the threshold
        large_list = [{"type": "text", "text": "z" * (_RESERVE * 4 + 100)}]
        ctx, full = filter_tool_output(large_list, _RESERVE, tmp_path)
        assert isinstance(ctx, str)
        assert "OUTPUT TRUNCATED" in ctx
        assert full == "__list__:" + json.dumps(large_list)

    def test_context_result_mentions_read_tool(self, tmp_path):
        ctx, _ = filter_tool_output(self._large(), _RESERVE, tmp_path)
        assert "read" in ctx.lower()


class TestErrorHandling:
    """Disk errors fail open — return original result, no crash."""

    def test_mkdir_failure_returns_original(self, tmp_path):
        bad_dir = tmp_path / "no_perms"
        with patch("tools.output_filter.Path.mkdir", side_effect=OSError("permission denied")):
            large = "z" * (_RESERVE * 4 + 1)
            ctx, full = filter_tool_output(large, _RESERVE, bad_dir)
        assert ctx == large   # unfiltered pass-through
        assert full == large

    def test_write_failure_returns_original(self, tmp_path):
        with patch("builtins.open", side_effect=OSError("disk full")):
            large = "z" * (_RESERVE * 4 + 1)
            ctx, full = filter_tool_output(large, _RESERVE, tmp_path)
        assert ctx == large

    def test_zero_reserve_tokens_skips_filtering(self, tmp_path):
        large = "z" * 9999
        ctx, full = filter_tool_output(large, reserve_tokens=0, temp_dir=tmp_path)
        assert ctx == large
        assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 1.2 — Run tests to confirm they all fail**

```
conda run -n dagi python -m pytest tests/test_output_filter.py -v
```

Expected: `ImportError: cannot import name 'filter_tool_output' from 'tools.output_filter'` (module doesn't exist yet).

- [ ] **Step 1.3 — Create `tools/output_filter.py`**

```python
"""
tools/output_filter.py — Filter large tool outputs before they enter LLM context.

If a tool result exceeds the token threshold, the full output is saved to a temp
file and a truncated preview + pointer is placed in context instead. This prevents
context-window overflow caused by unexpectedly large tool outputs (grep on a huge
codebase, bash with verbose output, read on a multi-MB file, etc.).

Public API
----------
filter_tool_output(result, reserve_tokens, temp_dir) -> (context_result, full_str)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

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
    temp_dir: Path,
) -> tuple[str | list, str]:
    """
    Filter a tool result before it enters LLM context.

    Parameters
    ----------
    result        : Raw value returned by registry.dispatch() after sentinel handling.
    reserve_tokens: Token budget threshold from AgentConfig (same field used for
                    compaction). Results >= this many estimated tokens are filtered.
    temp_dir      : Directory where the full output is saved when filtering fires.
                    Created automatically if it does not exist.

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

    # ── Result is large: write to temp file, build truncated context message ──
    try:
        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=temp_dir, prefix="tool_output_", suffix=".txt"
        )
        os.close(fd)
        Path(tmp_path).write_text(full_str, encoding="utf-8")
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

- [ ] **Step 1.4 — Run tests again — all should pass**

```
conda run -n dagi python -m pytest tests/test_output_filter.py -v
```

Expected: all green. If `test_mkdir_failure_returns_original` or `test_write_failure_returns_original` fail, the mock patches may need adjusting — `patch("tools.output_filter.Path.mkdir", ...)` patches the method on the class; alternatively use `patch.object`.

- [ ] **Step 1.5 — Commit**

```
git add tools/output_filter.py tests/test_output_filter.py
git commit -m "feat: add filter_tool_output() — truncates large tool results before context entry"
```

---

## Task 2: Wire the filter into `agent/loop.py`

**Files:**
- Modify: `agent/loop.py` lines 556–568

The call site is the block immediately after the sentinel `if/elif` chain, before
`result_str` is built.

### Step 2.1 — Write a failing integration test

Add a new test class to `tests/test_output_filter.py` that verifies the loop wires
the filter correctly (without spinning up a real LLM). Append this class to the file:

```python
class TestLoopIntegration:
    """
    Verify that AgentLoop feeds context_result (not full_str) into _messages
    and full_str (not context_result) into tracker.record_tool_end.
    """

    def _make_loop(self, tmp_path):
        """Build a minimal AgentLoop with mocked LLM and tracker."""
        from unittest.mock import MagicMock, patch
        from agent.loop import AgentLoop, AgentConfig

        cfg = AgentConfig(
            name="test",
            model="gpt-4o",
            api_url="http://localhost",
            api_key="test",
            reserve_tokens=100,   # 100 tokens → 400 chars threshold
            project_path=tmp_path,
        )
        with patch("agent.loop.openai.OpenAI"):
            loop = AgentLoop(cfg)
        return loop

    def test_large_result_filtered_in_messages(self, tmp_path):
        from unittest.mock import MagicMock, patch, call
        from agent.loop import AgentLoop, AgentConfig

        cfg = AgentConfig(
            name="test", model="gpt-4o", api_url="http://localhost",
            api_key="test", reserve_tokens=100, project_path=tmp_path,
        )
        with patch("agent.loop.openai.OpenAI"):
            loop = AgentLoop(cfg)

        large_output = "z" * 500   # 500 chars > 100*4=400 threshold
        loop.registry = MagicMock()
        loop.registry.dispatch.return_value = large_output
        loop.registry._tools = {}

        # Build a minimal fake API response with one tool call
        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "bash"
        tc.function.arguments = "{}"
        message = MagicMock()
        message.tool_calls = [tc]
        message.content = None
        response = MagicMock()
        response.choices = [MagicMock(message=message, finish_reason="tool_calls")]
        response.usage = MagicMock(
            prompt_tokens=10, completion_tokens=5, cost=None,
            completion_tokens_details=MagicMock(reasoning_tokens=0),
        )

        loop.tracker = MagicMock()
        loop.callbacks = MagicMock()

        # Patch _compact_context to be a no-op; AWAIT_USER_FLAG to end the loop
        from agent.loop import AWAIT_USER_FLAG

        def fake_api_call(*args, **kwargs):
            # First call returns the tool-call response; second returns exit flag
            if loop.registry.dispatch.call_count == 0:
                return response
            end = MagicMock()
            end_msg = MagicMock()
            end_msg.tool_calls = None
            end_msg.content = AWAIT_USER_FLAG
            end.choices = [MagicMock(message=end_msg, finish_reason="stop")]
            end.usage = response.usage
            return end

        loop._client = MagicMock()
        loop._client.chat.completions.create.side_effect = [response, MagicMock(
            choices=[MagicMock(message=MagicMock(
                tool_calls=None, content=AWAIT_USER_FLAG
            ), finish_reason="stop")],
            usage=response.usage,
        )]

        loop.run("test task")

        # The content added to _messages must be the filtered string (truncated),
        # not the original large_output verbatim.
        tool_messages = [
            m for m in loop._messages
            if m.get("role") == "tool"
        ]
        assert len(tool_messages) == 1
        content = tool_messages[0]["content"]
        assert isinstance(content, str)
        assert "OUTPUT TRUNCATED" in content
        assert large_output not in content   # not the full string

        # Tracker must have received the full string
        loop.tracker.record_tool_end.assert_called_once()
        _, full_arg = loop.tracker.record_tool_end.call_args[0]
        assert full_arg == large_output
```

- [ ] **Step 2.2 — Run the integration test to confirm it fails**

```
conda run -n dagi python -m pytest tests/test_output_filter.py::TestLoopIntegration -v
```

Expected: FAIL — `tool_messages[0]["content"]` equals the raw `large_output` (filter not wired yet).

- [ ] **Step 2.3 — Add the import to `agent/loop.py`**

In `agent/loop.py`, find the imports block (top of file). After the existing `tools/` imports (around line 18–20), add:

```python
from tools.output_filter import filter_tool_output
```

- [ ] **Step 2.4 — Replace the result dispatch block in `agent/loop.py`**

Find this exact block (lines 556–568):

```python
                    result_str = result if isinstance(result, str) else "__list__:" + json.dumps(result)
                    self.callbacks.on_tool_end(tc.function.name, result_str)
                    self.tracker.record_tool_end(tc.function.name, result_str)

                    tool_records.append(ToolCallRecord(
                        name=tc.function.name,
                        description=description,
                        input=tc.function.arguments,
                        result=result_str,
                    ))
                    self._messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result}
                    )
```

Replace with:

```python
                    # ── Output filter ────────────────────────────────────────
                    _filter_temp = DAGI_ROOT / ".dagi" / "temp"
                    context_result, full_str = filter_tool_output(
                        result, self.config.reserve_tokens, _filter_temp
                    )
                    if context_result is not result:
                        # Filtering fired — warn the user via the assistant text stream
                        self.callbacks.on_assistant_text(
                            f"[output filter] Tool result was large and has been truncated. "
                            f"Full output saved to {_filter_temp}."
                        )
                    # ─────────────────────────────────────────────────────────
                    result_str = (
                        context_result if isinstance(context_result, str)
                        else "__list__:" + json.dumps(context_result)
                    )
                    self.callbacks.on_tool_end(tc.function.name, result_str)   # filtered
                    self.tracker.record_tool_end(tc.function.name, full_str)    # full (JSONL)

                    tool_records.append(ToolCallRecord(
                        name=tc.function.name,
                        description=description,
                        input=tc.function.arguments,
                        result=full_str,                                        # full (JSONL)
                    ))
                    self._messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": context_result}
                    )
```

- [ ] **Step 2.5 — Run the integration test — should pass**

```
conda run -n dagi python -m pytest tests/test_output_filter.py::TestLoopIntegration -v
```

Expected: PASS.

- [ ] **Step 2.6 — Run the full test suite — no regressions**

```
conda run -n dagi python -m pytest tests/ -v
```

Expected: all existing tests still pass. If `test_tool_filter.py` or `test_continuation.py` show failures, the mock setup in those tests may need `full_str` vs `result_str` parameter updates — check that `tracker.record_tool_end` call assertions still match.

- [ ] **Step 2.7 — Commit**

```
git add agent/loop.py
git commit -m "feat: wire filter_tool_output into AgentLoop dispatch — large tool results now truncated in context"
```

---

## Task 3: Add `config.yaml` documentation

**Files:**
- Modify: `config.example.yaml`

The filter re-uses `reserve_tokens` — no new field needed. But users should know
the field now has a second effect. Add one comment line to the existing `reserve_tokens`
entry.

- [ ] **Step 3.1 — Update `config.example.yaml`**

Find this line in `config.example.yaml`:

```yaml
reserve_tokens: 16384        # Tokens held back for the assistant's next reply and the
                             # compaction summary itself. Compaction fires when
                             # prompt_tokens > context_window - reserve_tokens.
```

Replace with:

```yaml
reserve_tokens: 16384        # Tokens held back for the assistant's next reply and the
                             # compaction summary itself. Compaction fires when
                             # prompt_tokens > context_window - reserve_tokens.
                             # Also used as the output-filter threshold: tool results
                             # >= reserve_tokens tokens are truncated to reserve_tokens/2
                             # tokens in context; full output is saved to .dagi/temp/.
```

- [ ] **Step 3.2 — Commit**

```
git add config.example.yaml
git commit -m "docs: document output-filter behaviour on reserve_tokens in config.example.yaml"
```

---

## Self-Review

**Spec coverage:**
- ✅ Filter layer between tool output and context → Task 1 (`filter_tool_output`) + Task 2 (call site)
- ✅ `reserve_tokens` as threshold → Task 1 step 1.3
- ✅ Save to `.dagi/temp/tool_output_{prefix}.txt` → Task 1 step 1.3
- ✅ First `reserve_tokens/2` tokens as preview → Task 1 step 1.3
- ✅ Pointer + chunk-read instruction in context → Task 1 step 1.3
- ✅ JSONL tracker gets full output → Task 2 step 2.4
- ✅ TUI callback gets filtered output → Task 2 step 2.4
- ✅ Fail open on disk error → Task 1 step 1.3 + tests
- ✅ `reserve_tokens == 0` guard → Task 1 step 1.3 + test
- ✅ List/multimodal results handled → Task 1 step 1.3 (`_serialise`)
- ✅ `config.yaml` documentation → Task 3

**Placeholder scan:** No TBDs. All code blocks are complete. ✅

**Type consistency:**
- `filter_tool_output` signature is `(str | list, int, Path) -> tuple[str | list, str]` — consistent across all tasks.
- `context_result` and `full_str` variable names are consistent between Task 1 tests and Task 2 call site.
- `_filter_temp` is a `Path` (from `DAGI_ROOT / ".dagi" / "temp"`), matching `temp_dir: Path` parameter. ✅
