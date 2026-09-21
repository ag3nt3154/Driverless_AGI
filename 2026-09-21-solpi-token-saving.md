# SoL-Pi Token-Saving Mechanisms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 4 token-saving mechanisms inspired by the SoL-Pi paper (arXiv:2609.20519) — Action Fusion, Compaction Cost Gate, ObservationPack (turn-aging), and Evidence-Preserving Reducer — to cut dagi's token traffic by ~40-50%.

**Architecture:** Each mechanism is independent and can be shipped separately. They target distinct overhead sources: Action Fusion eliminates unnecessary LLM round trips; the Cost Gate prevents wasteful compaction; ObservationPack ages large observations out of context; the Reducer compresses build/test logs via the worker model. All four compose through the existing `_tool_dispatch.py` → `output_filter.py` → `_compaction.py` pipeline.

**Tech Stack:** Python 3.14, pytest, existing dagi harness (OpenAI chat completions API, session log, surface projection, subagent subprocess system)

---

## Mechanism 1: Action Fusion

### Task 1.1: Add `then_run` parameter to `WriteTool`

**Files:**
- Modify: `tools/write/_write.py`
- Test: `tests/test_action_fusion.py`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_action_fusion.py — Action Fusion: edit/write + follow-up command."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.write._write import WriteTool


class TestWriteThenRun:
    def test_write_only_returns_write_confirmation(self, tmp_path):
        tool = WriteTool(cwd=tmp_path)
        result = tool.run(path="hello.py", content="print('hi')")
        assert "Written" in result
        assert "---" not in result

    def test_then_run_appends_command_output(self, tmp_path):
        tool = WriteTool(cwd=tmp_path)
        result = tool.run(
            path="hello.py",
            content="print('hello from fusion')",
            then_run="python hello.py",
        )
        assert "Written" in result
        assert "--- then_run ---" in result
        assert "hello from fusion" in result

    def test_then_run_includes_exit_code_on_failure(self, tmp_path):
        tool = WriteTool(cwd=tmp_path)
        result = tool.run(
            path="bad.py",
            content="raise SystemExit(1)",
            then_run="python bad.py",
        )
        assert "exit code 1" in result

    def test_then_run_timeout_defaults_to_120(self, tmp_path):
        tool = WriteTool(cwd=tmp_path)
        # Just verify the parameter is accepted — timeout behaviour is tested
        # via BashTool's own tests.
        result = tool.run(
            path="fast.py", content="print('ok')", then_run="python fast.py"
        )
        assert "ok" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_action_fusion.py -v`
Expected: FAIL — `WriteTool.run()` does not accept `then_run`

- [ ] **Step 3: Implement `then_run` on WriteTool**

In `tools/write/_write.py`, add the `then_run` parameter to the schema and `run()`:

```python
from pathlib import Path
import subprocess
import sys

from agent.base_tool import BaseTool
from tools._path_guard import validate_path


class WriteTool(BaseTool):
    name = "write"
    description = (
        "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. "
        "Automatically creates parent directories. Paths are relative to the project root. "
        "Optional then_run executes a follow-up command after the write and returns combined output, "
        "saving one round trip."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to write (relative to project root, or absolute)"},
            "content": {"type": "string", "description": "Content to write to the file"},
            "then_run": {"type": "string", "description": "Shell command to run after writing (e.g. 'pytest tests/foo.py'). Output is appended to the result."},
        },
        "required": ["path", "content"],
    }

    _THEN_RUN_TIMEOUT = 120.0

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(self, path: str, content: str, then_run: str | None = None) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="\n")
        write_msg = f"Written {len(content)} characters to {p}"

        if then_run is None:
            return write_msg

        popen_kwargs: dict = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        try:
            proc = subprocess.Popen(
                then_run, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                cwd=str(self.cwd), **popen_kwargs,
            )
            stdout, stderr = proc.communicate(timeout=self._THEN_RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return f"{write_msg}\n--- then_run ---\n[timed out after {self._THEN_RUN_TIMEOUT}s]"

        cmd_output = (stdout or "") + (stderr or "")
        if proc.returncode != 0:
            cmd_output += f"\n[exit code {proc.returncode}]"
        return f"{write_msg}\n--- then_run ---\n{cmd_output or '[no output]'}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_action_fusion.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_action_fusion.py tools/write/_write.py
git commit -m "feat: add then_run (Action Fusion) to WriteTool"
```

### Task 1.2: Add `then_run` parameter to `EditTool`

**Files:**
- Modify: `tools/edit/_edit.py`
- Test: `tests/test_action_fusion.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_action_fusion.py`:

```python
from tools.edit._edit import EditTool


class TestEditThenRun:
    def test_edit_only_returns_edit_confirmation(self, tmp_path):
        (tmp_path / "f.py").write_text("old", encoding="utf-8")
        tool = EditTool(cwd=tmp_path)
        result = tool.run(path="f.py", oldText="old", newText="new")
        assert "Edited" in result
        assert "--- then_run ---" not in result

    def test_then_run_appends_command_output(self, tmp_path):
        (tmp_path / "f.py").write_text("print('before')", encoding="utf-8")
        tool = EditTool(cwd=tmp_path)
        result = tool.run(
            path="f.py",
            oldText="print('before')",
            newText="print('after')",
            then_run="python f.py",
        )
        assert "Edited" in result
        assert "after" in result

    def test_then_run_skipped_on_edit_error(self, tmp_path):
        (tmp_path / "f.py").write_text("aaa", encoding="utf-8")
        tool = EditTool(cwd=tmp_path)
        result = tool.run(
            path="f.py", oldText="MISSING", newText="new", then_run="echo SHOULD_NOT_RUN"
        )
        assert "Error" in result
        assert "SHOULD_NOT_RUN" not in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_action_fusion.py::TestEditThenRun -v`
Expected: FAIL — `EditTool.run()` does not accept `then_run`

- [ ] **Step 3: Implement `then_run` on EditTool**

The `then_run` subprocess logic is identical between WriteTool and EditTool. Extract a shared helper into `tools/_then_run.py`:

```python
"""tools/_then_run.py — Shared follow-up command execution for Action Fusion."""
from __future__ import annotations

import subprocess
import sys

from pathlib import Path

_THEN_RUN_TIMEOUT = 120.0


def execute_then_run(command: str, cwd: Path) -> str:
    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(
            command, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(cwd), **popen_kwargs,
        )
        stdout, stderr = proc.communicate(timeout=_THEN_RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return f"[timed out after {_THEN_RUN_TIMEOUT}s]"

    output = (stdout or "") + (stderr or "")
    if proc.returncode != 0:
        output += f"\n[exit code {proc.returncode}]"
    return output or "[no output]"
```

Update `WriteTool` in `tools/write/_write.py` to use the shared helper:

```python
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path
from tools._then_run import execute_then_run


class WriteTool(BaseTool):
    name = "write"
    description = (
        "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. "
        "Automatically creates parent directories. Paths are relative to the project root. "
        "Optional then_run executes a follow-up command after the write and returns combined output, "
        "saving one round trip."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to write (relative to project root, or absolute)"},
            "content": {"type": "string", "description": "Content to write to the file"},
            "then_run": {"type": "string", "description": "Shell command to run after writing (e.g. 'pytest tests/foo.py'). Output is appended to the result."},
        },
        "required": ["path", "content"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(self, path: str, content: str, then_run: str | None = None) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="\n")
        write_msg = f"Written {len(content)} characters to {p}"

        if then_run is None:
            return write_msg
        return f"{write_msg}\n--- then_run ---\n{execute_then_run(then_run, self.cwd)}"
```

Update `EditTool` in `tools/edit/_edit.py`:

```python
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path
from tools._then_run import execute_then_run


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Edit a file by replacing exact text. The oldText must match exactly "
        "(including whitespace). Use this for precise, surgical edits. "
        "Paths are relative to the project root. "
        "Optional then_run executes a follow-up command after the edit and returns combined output."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to edit (relative to project root, or absolute)"},
            "oldText": {"type": "string", "description": "Exact text to find and replace (must match exactly)"},
            "newText": {"type": "string", "description": "New text to replace the old text with"},
            "then_run": {"type": "string", "description": "Shell command to run after editing (e.g. 'pytest tests/foo.py'). Output is appended to the result."},
        },
        "required": ["path", "oldText", "newText"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(self, path: str, oldText: str, newText: str, then_run: str | None = None) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)
        content = p.read_text(encoding="utf-8")
        old_norm = oldText.replace("\r\n", "\n").replace("\r", "\n")
        new_norm = newText.replace("\r\n", "\n").replace("\r", "\n")
        count = content.count(old_norm)
        if count == 0:
            return f"Error: oldText not found in {p}"
        if count > 1:
            return f"Error: oldText found {count} times in {p} — must be unique"
        p.write_text(content.replace(old_norm, new_norm, 1), encoding="utf-8", newline="\n")
        edit_msg = f"Edited {p}"

        if then_run is None:
            return edit_msg
        return f"{edit_msg}\n--- then_run ---\n{execute_then_run(then_run, self.cwd)}"
```

- [ ] **Step 4: Run all Action Fusion tests**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_action_fusion.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Run existing write/edit tests to check for regressions**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_write_tool.py tests/test_edit_tool.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tools/_then_run.py tools/write/_write.py tools/edit/_edit.py tests/test_action_fusion.py
git commit -m "feat: add then_run to EditTool; extract shared _then_run helper"
```

---

## Mechanism 2: Compaction Cost Gate

### Task 2.1: Implement the cost gate in `_compaction.py`

The existing compaction trigger fires whenever `prompt_tokens > context_window - reserve_tokens`. The cost gate adds an economic check: *will the token savings from compacting outweigh the cost of the summarization call?*

**How the cost gate works:**

1. Estimate how many more LLM requests remain in this turn (`remaining_requests = unfinished_steps × avg_requests_per_step`).
2. Estimate tokens saved per future request = `(prompt_tokens - estimated_post_compact_tokens)`.
3. Projected savings = `remaining_requests × tokens_saved_per_request`.
4. Compaction cost = tokens consumed by the summarization call itself (~`prompt_tokens` input + summary output).
5. Gate passes when `projected_savings > compaction_cost`.
6. Emergency override: if `prompt_tokens > context_window - reserve_tokens`, compact regardless (existing behaviour preserved).

**Files:**
- Create: `agent/_compaction_gate.py`
- Modify: `agent/loop.py` (compaction trigger at lines 850-857)
- Test: `tests/test_compaction_gate.py`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_compaction_gate.py — Cost gate for context compaction."""
from __future__ import annotations

import pytest

from agent._compaction_gate import should_compact


class TestCostGate:
    def test_below_emergency_threshold_and_no_savings(self):
        assert should_compact(
            prompt_tokens=50_000,
            context_window=128_000,
            reserve_tokens=16_384,
            avg_requests_per_step=3,
            unfinished_steps=1,
            estimated_reduction_ratio=0.5,
            compaction_generation=0,
        ) is False

    def test_above_emergency_threshold_always_compacts(self):
        assert should_compact(
            prompt_tokens=120_000,
            context_window=128_000,
            reserve_tokens=16_384,
            avg_requests_per_step=3,
            unfinished_steps=2,
            estimated_reduction_ratio=0.5,
            compaction_generation=0,
        ) is True

    def test_moderate_fill_with_many_remaining_steps_compacts(self):
        assert should_compact(
            prompt_tokens=90_000,
            context_window=128_000,
            reserve_tokens=16_384,
            avg_requests_per_step=5,
            unfinished_steps=10,
            estimated_reduction_ratio=0.5,
            compaction_generation=0,
        ) is True

    def test_moderate_fill_with_few_remaining_steps_skips(self):
        assert should_compact(
            prompt_tokens=70_000,
            context_window=128_000,
            reserve_tokens=16_384,
            avg_requests_per_step=2,
            unfinished_steps=1,
            estimated_reduction_ratio=0.5,
            compaction_generation=0,
        ) is False

    def test_later_compactions_require_larger_margins(self):
        # First compaction passes at this fill level
        assert should_compact(
            prompt_tokens=85_000,
            context_window=128_000,
            reserve_tokens=16_384,
            avg_requests_per_step=4,
            unfinished_steps=5,
            estimated_reduction_ratio=0.5,
            compaction_generation=0,
        ) is True
        # Same parameters but generation=2 — previous rewrite costs not recovered
        assert should_compact(
            prompt_tokens=85_000,
            context_window=128_000,
            reserve_tokens=16_384,
            avg_requests_per_step=4,
            unfinished_steps=5,
            estimated_reduction_ratio=0.5,
            compaction_generation=2,
        ) is False

    def test_zero_unfinished_steps_never_compacts_unless_emergency(self):
        assert should_compact(
            prompt_tokens=90_000,
            context_window=128_000,
            reserve_tokens=16_384,
            avg_requests_per_step=3,
            unfinished_steps=0,
            estimated_reduction_ratio=0.5,
            compaction_generation=0,
        ) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_compaction_gate.py -v`
Expected: FAIL — module `agent._compaction_gate` does not exist

- [ ] **Step 3: Implement the cost gate**

Create `agent/_compaction_gate.py`:

```python
"""agent/_compaction_gate.py — Economic cost gate for context compaction.

Decides whether compacting now will save more tokens across remaining requests
than the compaction call itself costs. Emergency compaction (context window
nearly full) always fires regardless of the gate.
"""
from __future__ import annotations


def should_compact(
    *,
    prompt_tokens: int,
    context_window: int,
    reserve_tokens: int,
    avg_requests_per_step: float,
    unfinished_steps: int,
    estimated_reduction_ratio: float,
    compaction_generation: int,
) -> bool:
    """Return True when compaction is economically justified or urgent.

    Parameters
    ----------
    prompt_tokens : Current prompt token count.
    context_window : Model's hard token limit.
    reserve_tokens : Headroom kept for response + summary.
    avg_requests_per_step : Observed average LLM requests per completed step.
    unfinished_steps : Steps remaining in the current plan/turn.
    estimated_reduction_ratio : Fraction of prompt tokens expected to survive
        compaction (0.3 = compacted context is ~30% of original).
    compaction_generation : Number of compactions already performed this session.
        Later compactions require larger savings margins because earlier rewrite
        costs have not been fully amortised.
    """
    budget = context_window - reserve_tokens
    if budget <= 0:
        return False

    # Emergency: context window nearly full — always compact
    if prompt_tokens > budget:
        return True

    if unfinished_steps <= 0:
        return False

    remaining_requests = max(avg_requests_per_step * unfinished_steps, 1.0)
    tokens_freed = prompt_tokens * (1.0 - estimated_reduction_ratio)
    projected_savings = remaining_requests * tokens_freed

    # Compaction cost: reading the full context + generating a summary.
    # Approximate summary output as 20% of the freed tokens.
    compaction_cost = prompt_tokens + tokens_freed * 0.2

    # Later compactions require progressively larger margins — each prior
    # compaction's rewrite cost was not fully recovered.
    margin_multiplier = 1.0 + 0.5 * compaction_generation

    return projected_savings > compaction_cost * margin_multiplier
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_compaction_gate.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/_compaction_gate.py tests/test_compaction_gate.py
git commit -m "feat: add compaction cost gate (should_compact)"
```

### Task 2.2: Wire the cost gate into the agent loop

**Files:**
- Modify: `agent/loop.py` (compaction trigger, lines 850-857 and pre-request guard 614-631)
- Modify: `agent/_loop_config.py` (add `estimated_reduction_ratio` config field)

- [ ] **Step 1: Add config field**

In `agent/_loop_config.py`, add to `AgentConfig`:

```python
    # Compaction cost gate: estimated fraction of tokens surviving compaction.
    # 0.3 means the compacted context is ~30% of the original.
    estimated_reduction_ratio: float = 0.3
```

- [ ] **Step 2: Add step-tracking state to the loop**

In `agent/loop.py`, in `AgentLoop.__init__()`, add tracking fields:

```python
        self._completed_step_count: int = 0
        self._total_requests_in_completed_steps: int = 0
```

And at the end of `_continuing_step_finished()`, increment them:

```python
        self._completed_step_count += 1
        self._total_requests_in_completed_steps += 1  # at least 1 request per step
```

- [ ] **Step 3: Replace the threshold-only trigger with the cost gate**

Replace the compaction trigger block at lines 850-857 of `agent/loop.py`:

```python
                # ── Compaction trigger ────────────────────────────────────────
                if self.config.context_window > 0 and _prompt_tok > 0:
                    from agent._compaction_gate import should_compact

                    _avg_rps = (
                        self._total_requests_in_completed_steps
                        / max(self._completed_step_count, 1)
                    )
                    # Estimate unfinished steps from plan or default to 3
                    _unfinished = 3
                    if should_compact(
                        prompt_tokens=_prompt_tok,
                        context_window=self.config.context_window,
                        reserve_tokens=self.config.reserve_tokens,
                        avg_requests_per_step=_avg_rps,
                        unfinished_steps=_unfinished,
                        estimated_reduction_ratio=self.config.estimated_reduction_ratio,
                        compaction_generation=self._compaction_generation,
                    ):
                        self._compact_context()
                # ─────────────────────────────────────────────────────────────
```

Note: the pre-request budget guard (lines 614-631) keeps its existing emergency check unchanged — it fires when the estimated request exceeds the hard budget, which is the "emergency override" path.

- [ ] **Step 4: Run existing compaction tests to verify no regression**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_compaction_extract.py tests/test_compact_subagent.py tests/test_compact_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/loop.py agent/_loop_config.py
git commit -m "feat: wire compaction cost gate into agent loop"
```

---

## Mechanism 3: ObservationPack (Turn-Aging)

### Task 3.1: Track observation ages in the session log

Every `TOOL_RESULT` event on the surface needs an "age" — how many LLM requests have occurred since it was produced. After a configurable threshold (default: 2 requests), large observations are replaced with a compact handle + excerpt.

**Files:**
- Create: `agent/_observation_pack.py`
- Test: `tests/test_observation_pack.py`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_observation_pack.py — ObservationPack turn-aging of large observations."""
from __future__ import annotations

import pytest

from agent._observation_pack import ObservationTracker


class TestObservationTracker:
    def test_register_stores_full_content(self):
        tracker = ObservationTracker()
        tracker.register("call_1", "x" * 20_000, seq=10)
        assert tracker.get_full("call_1") == "x" * 20_000

    def test_small_observation_never_ages(self):
        tracker = ObservationTracker()
        tracker.register("call_1", "small", seq=10)
        tracker.tick()
        tracker.tick()
        tracker.tick()
        assert tracker.should_replace("call_1") is False

    def test_large_observation_ages_after_grace_period(self):
        tracker = ObservationTracker()
        tracker.register("call_1", "x" * 20_000, seq=10)
        tracker.tick()  # request 1 — within grace
        assert tracker.should_replace("call_1") is False
        tracker.tick()  # request 2 — within grace
        assert tracker.should_replace("call_1") is False
        tracker.tick()  # request 3 — past grace
        assert tracker.should_replace("call_1") is True

    def test_build_replacement_contains_handle_and_excerpt(self):
        tracker = ObservationTracker()
        content = "HEADER\n" + "x" * 20_000 + "\nFOOTER"
        tracker.register("call_1", content, seq=10)
        tracker.tick()
        tracker.tick()
        tracker.tick()
        replacement = tracker.build_replacement("call_1")
        assert "[observation archived]" in replacement
        assert "call_1" in replacement
        assert "HEADER" in replacement
        assert "FOOTER" in replacement
        assert len(replacement) < len(content)

    def test_custom_grace_period(self):
        tracker = ObservationTracker(grace_requests=1)
        tracker.register("call_1", "x" * 20_000, seq=10)
        tracker.tick()  # request 1 — within grace
        assert tracker.should_replace("call_1") is False
        tracker.tick()  # request 2 — past grace
        assert tracker.should_replace("call_1") is True

    def test_custom_size_threshold(self):
        tracker = ObservationTracker(size_threshold_chars=100)
        tracker.register("call_1", "x" * 99, seq=10)
        tracker.register("call_2", "x" * 101, seq=11)
        tracker.tick()
        tracker.tick()
        tracker.tick()
        assert tracker.should_replace("call_1") is False
        assert tracker.should_replace("call_2") is True

    def test_unknown_call_id_returns_false(self):
        tracker = ObservationTracker()
        assert tracker.should_replace("nonexistent") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_observation_pack.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement ObservationTracker**

Create `agent/_observation_pack.py`:

```python
"""agent/_observation_pack.py — Turn-aging for large tool observations.

Large tool results are kept verbatim for a grace period (default: 2 LLM
requests), then replaced on the surface with a compact handle + head/tail
excerpt. The full content remains retrievable via the hash cache.
"""
from __future__ import annotations

from dataclasses import dataclass, field

_DEFAULT_SIZE_THRESHOLD = 10 * 1024  # 10 KiB in chars
_DEFAULT_GRACE_REQUESTS = 2
_EXCERPT_CHARS = 1024


@dataclass
class _TrackedObservation:
    call_id: str
    content: str
    seq: int
    char_count: int
    age: int = 0  # LLM requests since registration


class ObservationTracker:
    """Track large observations and decide when to replace them with handles."""

    def __init__(
        self,
        size_threshold_chars: int = _DEFAULT_SIZE_THRESHOLD,
        grace_requests: int = _DEFAULT_GRACE_REQUESTS,
    ):
        self._threshold = size_threshold_chars
        self._grace = grace_requests
        self._observations: dict[str, _TrackedObservation] = {}

    def register(self, call_id: str, content: str, *, seq: int) -> None:
        self._observations[call_id] = _TrackedObservation(
            call_id=call_id,
            content=content,
            seq=seq,
            char_count=len(content),
        )

    def tick(self) -> None:
        for obs in self._observations.values():
            obs.age += 1

    def should_replace(self, call_id: str) -> bool:
        obs = self._observations.get(call_id)
        if obs is None:
            return False
        if obs.char_count < self._threshold:
            return False
        return obs.age > self._grace

    def get_full(self, call_id: str) -> str | None:
        obs = self._observations.get(call_id)
        return obs.content if obs else None

    def build_replacement(self, call_id: str) -> str:
        obs = self._observations[call_id]
        half = _EXCERPT_CHARS // 2
        head = obs.content[:half]
        tail = obs.content[-half:] if len(obs.content) > _EXCERPT_CHARS else ""
        return (
            f"[observation archived — handle: {call_id}, "
            f"original size: {obs.char_count:,} chars]\n"
            f"--- HEAD ---\n{head}\n"
            + (f"--- TAIL ---\n{tail}\n" if tail else "")
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_observation_pack.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/_observation_pack.py tests/test_observation_pack.py
git commit -m "feat: add ObservationTracker for turn-aging large observations"
```

### Task 3.2: Wire ObservationPack into the agent loop

The tracker needs to be:
1. Created in `AgentLoop.__init__`
2. Fed each tool result from `bookkeep_tool_call` (register)
3. Ticked on each API request
4. Applied as surface replacements before building the request message list

**Files:**
- Modify: `agent/loop.py` (init + `_build_request_messages`)
- Modify: `agent/_tool_dispatch.py` (`bookkeep_tool_call` — register observations)

- [ ] **Step 1: Add tracker to AgentLoop.__init__**

In `agent/loop.py`, add after the `_compaction_generation` line:

```python
        from agent._observation_pack import ObservationTracker
        self._observation_tracker = ObservationTracker()
```

- [ ] **Step 2: Register observations in `bookkeep_tool_call`**

In `agent/_tool_dispatch.py`, in `bookkeep_tool_call()`, after the `loop.log.append(sev.TOOL_RESULT, ...)` call (line 190-200), add:

```python
    if hasattr(loop, "_observation_tracker"):
        loop._observation_tracker.register(
            tc.id, result_str, seq=loop.log.seq
        )
```

- [ ] **Step 3: Tick and apply replacements in `_build_request_messages`**

In `agent/loop.py`, in `_build_request_messages()`, tick the tracker and apply replacements to the returned messages:

```python
    def _build_request_messages(self) -> list[dict]:
        msgs = list(self.log.surface.messages)
        header = self._build_header()
        if header:
            msgs.insert(0, header)

        if hasattr(self, "_observation_tracker"):
            self._observation_tracker.tick()
            for msg in msgs:
                if msg.get("role") == "tool":
                    call_id = msg.get("tool_call_id")
                    if call_id and self._observation_tracker.should_replace(call_id):
                        msg["content"] = self._observation_tracker.build_replacement(call_id)

        return msgs
```

- [ ] **Step 4: Run the full test suite to check for regressions**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/ -x --timeout=60 -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/loop.py agent/_tool_dispatch.py
git commit -m "feat: wire ObservationPack into agent loop"
```

### Task 3.3: Add `retrieve_observation` tool

The agent needs a way to page back into archived observations. This is a lightweight tool that reads from the ObservationTracker.

**Files:**
- Create: `tools/retrieve_observation/_retrieve_observation.py`
- Test: `tests/test_observation_pack.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_observation_pack.py`:

```python
from tools.retrieve_observation._retrieve_observation import RetrieveObservationTool
from agent._observation_pack import ObservationTracker


class TestRetrieveObservationTool:
    def test_retrieves_full_content(self):
        tracker = ObservationTracker()
        tracker.register("call_1", "full content here", seq=1)
        tool = RetrieveObservationTool(tracker)
        result = tool.run(handle="call_1")
        assert result == "full content here"

    def test_retrieves_page(self):
        tracker = ObservationTracker()
        content = "line1\nline2\nline3\nline4\nline5"
        tracker.register("call_1", content, seq=1)
        tool = RetrieveObservationTool(tracker)
        result = tool.run(handle="call_1", offset=0, limit=2)
        lines = result.strip().split("\n")
        assert lines[0] == "line1"
        assert lines[1] == "line2"

    def test_unknown_handle_returns_error(self):
        tracker = ObservationTracker()
        tool = RetrieveObservationTool(tracker)
        result = tool.run(handle="nonexistent")
        assert "not found" in result.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_observation_pack.py::TestRetrieveObservationTool -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement the tool**

Create directory and file `tools/retrieve_observation/_retrieve_observation.py`:

```python
"""tools/retrieve_observation/_retrieve_observation.py — Retrieve archived observations."""
from __future__ import annotations

from typing import TYPE_CHECKING

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent._observation_pack import ObservationTracker


class RetrieveObservationTool(BaseTool):
    name = "retrieve_observation"
    description = (
        "Retrieve the full content (or a page of it) from an archived observation. "
        "Use the handle shown in '[observation archived]' messages."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "handle": {"type": "string", "description": "The observation handle (call ID)"},
            "offset": {"type": "integer", "description": "Line offset to start from (default 0)"},
            "limit": {"type": "integer", "description": "Number of lines to return (default: all)"},
        },
        "required": ["handle"],
    }

    def __init__(self, tracker: "ObservationTracker"):
        self._tracker = tracker

    def run(self, handle: str, offset: int = 0, limit: int | None = None) -> str:
        content = self._tracker.get_full(handle)
        if content is None:
            return f"Error: observation handle '{handle}' not found."
        lines = content.split("\n")
        end = offset + limit if limit is not None else len(lines)
        return "\n".join(lines[offset:end])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_observation_pack.py -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Register the tool in the tool registry**

The tool needs to be registered in whichever file creates the tool registry (likely `agent/registry.py` or the registry builder in `agent/loop.py`). Find the tool registration site and add:

```python
from tools.retrieve_observation._retrieve_observation import RetrieveObservationTool
# ... in the registration block:
registry.register(RetrieveObservationTool(self._observation_tracker))
```

- [ ] **Step 6: Commit**

```bash
git add tools/retrieve_observation/_retrieve_observation.py tests/test_observation_pack.py agent/loop.py
git commit -m "feat: add retrieve_observation tool for ObservationPack"
```

---

## Mechanism 4: Evidence-Preserving Reducer

### Task 4.1: Build the log reducer

The reducer takes build/test command output, sends it to the worker model for extraction, and verifies the result deterministically.

**Files:**
- Create: `tools/_log_reducer.py`
- Test: `tests/test_log_reducer.py`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_log_reducer.py — Evidence-Preserving Reducer for build/test logs."""
from __future__ import annotations

import json
import pytest

from tools._log_reducer import (
    is_reducible_command,
    verify_receipt,
    build_reducer_prompt,
    ReducerReceipt,
)


class TestCommandDetection:
    def test_pytest_is_reducible(self):
        assert is_reducible_command("pytest tests/ -v") is True

    def test_python_m_pytest_is_reducible(self):
        assert is_reducible_command("python -m pytest tests/") is True

    def test_npm_test_is_reducible(self):
        assert is_reducible_command("npm test") is True

    def test_make_is_reducible(self):
        assert is_reducible_command("make build") is True

    def test_cat_is_not_reducible(self):
        assert is_reducible_command("cat file.txt") is False

    def test_grep_is_not_reducible(self):
        assert is_reducible_command("grep -r pattern .") is False

    def test_echo_is_not_reducible(self):
        assert is_reducible_command("echo hello") is False


class TestVerifyReceipt:
    def test_valid_receipt_passes(self):
        original = "PASS test_one\nFAIL test_two\nError: something broke\n" + "x" * 5000
        receipt = ReducerReceipt(
            exit_status=1,
            summary="1 passed, 1 failed",
            evidence=["FAIL test_two", "Error: something broke"],
            original_size=len(original),
        )
        assert verify_receipt(receipt, original, exit_code=1) is True

    def test_wrong_exit_status_fails(self):
        original = "output" * 1000
        receipt = ReducerReceipt(
            exit_status=0,
            summary="all passed",
            evidence=["output"],
            original_size=len(original),
        )
        assert verify_receipt(receipt, original, exit_code=1) is False

    def test_evidence_not_in_original_fails(self):
        original = "actual output" * 1000
        receipt = ReducerReceipt(
            exit_status=0,
            summary="ok",
            evidence=["HALLUCINATED LINE"],
            original_size=len(original),
        )
        assert verify_receipt(receipt, original, exit_code=0) is False

    def test_wrong_original_size_fails(self):
        original = "x" * 5000
        receipt = ReducerReceipt(
            exit_status=0,
            summary="ok",
            evidence=[],
            original_size=9999,
        )
        assert verify_receipt(receipt, original, exit_code=0) is False

    def test_insufficient_compression_fails(self):
        original = "x" * 5000
        receipt = ReducerReceipt(
            exit_status=0,
            summary="x" * 4900,  # barely compressed
            evidence=[],
            original_size=len(original),
        )
        assert verify_receipt(receipt, original, exit_code=0) is False


class TestBuildReducerPrompt:
    def test_prompt_includes_log_content(self):
        prompt = build_reducer_prompt("FAIL test_foo\nsome output", exit_code=1)
        assert "FAIL test_foo" in prompt
        assert "exit_code" in prompt.lower() or "exit code" in prompt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_log_reducer.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement the reducer**

Create `tools/_log_reducer.py`:

```python
"""tools/_log_reducer.py — Evidence-Preserving Reducer for build/test logs.

Compresses verbose build/test output into compact receipts using the worker
model, with deterministic verification that key evidence is preserved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_REDUCIBLE_PATTERNS = [
    re.compile(r"\bpytest\b"),
    re.compile(r"\bunittest\b"),
    re.compile(r"\bnpm\s+(test|run\s+test)\b"),
    re.compile(r"\byarn\s+test\b"),
    re.compile(r"\bmake\b"),
    re.compile(r"\bcmake\b"),
    re.compile(r"\bcargo\s+(test|build|check)\b"),
    re.compile(r"\bgo\s+(test|build)\b"),
    re.compile(r"\bgcc\b|\bg\+\+\b|\bclang\b"),
    re.compile(r"\bmvn\b|\bgradle\b"),
    re.compile(r"\btox\b|\bnox\b"),
    re.compile(r"\bpython\s+-m\s+pytest\b"),
]

_MIN_LOG_CHARS = 4 * 1024  # 4 KiB — don't bother reducing short logs
_MIN_COMPRESSION_RATIO = 0.5  # receipt must be < 50% of original size


def is_reducible_command(command: str) -> bool:
    return any(p.search(command) for p in _REDUCIBLE_PATTERNS)


@dataclass(frozen=True, slots=True)
class ReducerReceipt:
    exit_status: int
    summary: str
    evidence: list[str]
    original_size: int

    def to_context_str(self) -> str:
        evidence_block = "\n".join(f"  > {line}" for line in self.evidence)
        return (
            f"[build/test log reduced — original {self.original_size:,} chars]\n"
            f"Exit status: {self.exit_status}\n"
            f"Summary: {self.summary}\n"
            f"Key evidence:\n{evidence_block}"
        )


def verify_receipt(
    receipt: ReducerReceipt,
    original: str,
    exit_code: int,
) -> bool:
    if receipt.exit_status != exit_code:
        return False

    if receipt.original_size != len(original):
        return False

    for evidence_line in receipt.evidence:
        if evidence_line not in original:
            return False

    receipt_size = len(receipt.to_context_str())
    if receipt_size >= len(original) * _MIN_COMPRESSION_RATIO:
        return False

    return True


def build_reducer_prompt(log_content: str, exit_code: int) -> str:
    return (
        "Extract the key diagnostic information from this build/test log into a "
        "compact receipt. Respond with ONLY valid JSON matching this schema:\n"
        "{\n"
        '  "exit_status": <integer>,\n'
        '  "summary": "<one-line summary of what happened>",\n'
        '  "evidence": ["<exact line from the log>", ...]\n'
        "}\n\n"
        "Rules:\n"
        "- exit_status must match the actual exit code\n"
        "- evidence lines must be EXACT substrings from the log\n"
        "- Include all error messages, failure descriptions, and assertion messages\n"
        "- Include test counts (passed/failed/skipped) if present\n"
        "- Do NOT paraphrase — quote exactly\n\n"
        f"Exit code: {exit_code}\n\n"
        f"--- LOG START ---\n{log_content}\n--- LOG END ---"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_log_reducer.py -v`
Expected: PASS (all 11 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/_log_reducer.py tests/test_log_reducer.py
git commit -m "feat: add Evidence-Preserving Reducer (log reducer + verification)"
```

### Task 4.2: Wire the reducer into BashTool's output pipeline

The reducer fires when: (1) the command matches `is_reducible_command`, (2) the output exceeds `_MIN_LOG_CHARS` (4 KiB), and (3) a worker model config is available. It runs the worker model inline (via the subagent system), verifies the receipt, and replaces the output. On verification failure, the original output passes through unchanged.

**Files:**
- Modify: `agent/_tool_dispatch.py` (between dispatch and bookkeep)
- Create: `agent/_reduce_dispatch.py` (reducer orchestration)
- Test: `tests/test_log_reducer.py` (append integration test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_log_reducer.py`:

```python
from unittest.mock import MagicMock, patch

from agent._reduce_dispatch import try_reduce_log


class TestReduceDispatch:
    def test_non_reducible_command_returns_none(self):
        result = try_reduce_log(
            command="cat file.txt",
            output="some output" * 1000,
            exit_code=0,
            worker_config=MagicMock(),
            project_path="/tmp",
        )
        assert result is None

    def test_short_output_returns_none(self):
        result = try_reduce_log(
            command="pytest tests/",
            output="short",
            exit_code=0,
            worker_config=MagicMock(),
            project_path="/tmp",
        )
        assert result is None

    def test_no_worker_config_returns_none(self):
        result = try_reduce_log(
            command="pytest tests/",
            output="x" * 10_000,
            exit_code=0,
            worker_config=None,
            project_path="/tmp",
        )
        assert result is None

    @patch("agent._reduce_dispatch._call_worker_model")
    def test_valid_receipt_returns_reduced_output(self, mock_call):
        original = "PASS test_a\nFAIL test_b\nError: boom\n" + "x" * 10_000
        mock_call.return_value = {
            "exit_status": 1,
            "summary": "1 passed, 1 failed",
            "evidence": ["FAIL test_b", "Error: boom"],
        }
        result = try_reduce_log(
            command="pytest tests/",
            output=original,
            exit_code=1,
            worker_config=MagicMock(),
            project_path="/tmp",
        )
        assert result is not None
        assert "reduced" in result.lower()
        assert "FAIL test_b" in result

    @patch("agent._reduce_dispatch._call_worker_model")
    def test_failed_verification_falls_back_to_none(self, mock_call):
        original = "actual output\n" + "x" * 10_000
        mock_call.return_value = {
            "exit_status": 0,
            "summary": "ok",
            "evidence": ["HALLUCINATED"],  # not in original
        }
        result = try_reduce_log(
            command="pytest tests/",
            output=original,
            exit_code=0,
            worker_config=MagicMock(),
            project_path="/tmp",
        )
        assert result is None

    @patch("agent._reduce_dispatch._call_worker_model")
    def test_worker_exception_falls_back_to_none(self, mock_call):
        mock_call.side_effect = Exception("API error")
        result = try_reduce_log(
            command="pytest tests/",
            output="x" * 10_000,
            exit_code=0,
            worker_config=MagicMock(),
            project_path="/tmp",
        )
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_log_reducer.py::TestReduceDispatch -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement the dispatch orchestrator**

Create `agent/_reduce_dispatch.py`:

```python
"""agent/_reduce_dispatch.py — Reducer dispatch for build/test tool output.

Orchestrates the Evidence-Preserving Reducer: checks if a command's output
is eligible, calls the worker model for extraction, verifies the receipt,
and returns the reduced output (or None to use the original).
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import openai

from tools._log_reducer import (
    ReducerReceipt,
    _MIN_LOG_CHARS,
    build_reducer_prompt,
    is_reducible_command,
    verify_receipt,
)

if TYPE_CHECKING:
    from agent._loop_config import AgentConfig


def _call_worker_model(prompt: str, worker_config: "AgentConfig") -> dict:
    client = openai.OpenAI(
        api_key=worker_config.api_key,
        base_url=worker_config.base_url,
    )
    response = client.chat.completions.create(
        model=worker_config.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    text = response.choices[0].message.content or ""
    # Strip markdown fences if present
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())


def try_reduce_log(
    *,
    command: str,
    output: str,
    exit_code: int,
    worker_config: "AgentConfig | None",
    project_path: str,
) -> str | None:
    """Try to reduce a command's output via the worker model.

    Returns the reduced output string on success, or None to signal the
    caller should use the original output unchanged.
    """
    if not is_reducible_command(command):
        return None
    if len(output) < _MIN_LOG_CHARS:
        return None
    if worker_config is None:
        return None

    try:
        prompt = build_reducer_prompt(output, exit_code)
        raw = _call_worker_model(prompt, worker_config)
        receipt = ReducerReceipt(
            exit_status=raw["exit_status"],
            summary=raw["summary"],
            evidence=raw.get("evidence", []),
            original_size=len(output),
        )
        if not verify_receipt(receipt, output, exit_code):
            return None
        return receipt.to_context_str()
    except Exception:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_log_reducer.py -v`
Expected: PASS (all 17 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/_reduce_dispatch.py tests/test_log_reducer.py
git commit -m "feat: add reducer dispatch orchestrator"
```

### Task 4.3: Integrate the reducer into the tool dispatch pipeline

The reducer fires in `dispatch_tool_calls` after `bash` tool execution but before `bookkeep_tool_call`, only for bash commands whose output is eligible.

**Files:**
- Modify: `agent/_tool_dispatch.py` (in `dispatch_tool_calls`, between dispatch and bookkeep)

- [ ] **Step 1: Add reducer call to dispatch_tool_calls**

In `agent/_tool_dispatch.py`, after the `result = loop.registry.dispatch(tc.function.name, args)` line (line 109) and after the side-effect unwrapping block (line 136), add:

```python
        # ── Evidence-Preserving Reducer ─────────────────────────────────
        if (
            tc.function.name == "bash"
            and isinstance(result, str)
            and hasattr(loop, "config")
            and loop.config.worker_config is not None
        ):
            from agent._reduce_dispatch import try_reduce_log

            _cmd = args.get("command", "")
            # Extract exit code from result suffix
            _exit_code = 0
            if result.endswith("]") and "[exit code " in result:
                try:
                    _exit_code = int(result.rsplit("[exit code ", 1)[1].rstrip("]").strip())
                except (ValueError, IndexError):
                    pass
            _reduced = try_reduce_log(
                command=_cmd,
                output=result,
                exit_code=_exit_code,
                worker_config=loop.config.worker_config,
                project_path=str(loop.config.project_path),
            )
            if _reduced is not None:
                result = _reduced
        # ────────────────────────────────────────────────────────────────
```

- [ ] **Step 2: Run existing tests to check for regressions**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/test_output_filter.py tests/test_compaction_extract.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add agent/_tool_dispatch.py
git commit -m "feat: wire Evidence-Preserving Reducer into bash tool dispatch"
```

---

## Final: Integration Verification

### Task 5.1: End-to-end regression check

- [ ] **Step 1: Run the full test suite**

Run: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest tests/ -x --timeout=120 -v`
Expected: PASS

- [ ] **Step 2: Update README.md and TODO.md**

Add a section to `README.md` documenting the four token-saving mechanisms. Update `TODO.md` to reflect the completed work.

- [ ] **Step 3: Final commit**

```bash
git add README.md TODO.md
git commit -m "docs: document SoL-Pi token-saving mechanisms"
```
