# Plan-Work-Review Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give worker/review subagents a fast-fail escalation channel to the main agent, and give the main agent a live, per-iteration plan status board in its system prompt — both without adding new bidirectional subprocess IPC or hurting `cache_prompt` hit rate.

**Architecture:** (A) A new `escalate_issue` tool writes a sidecar `<handoff-stem>_escalation.md` file; `tools/_subagent_runner.py`'s existing 2s poll loop detects it, terminates the subprocess, and returns `{"status": "escalated", ...}`; `tools/spawn_subagent.py` surfaces this as a tool result to the main agent. (B) `agent/loop.py` splits system-prompt assembly into a cached static prefix plus a small "Active Plan" + "Plan Status" tail that's rebuilt from `plan.md` at the top of every loop iteration, so the cached prefix is untouched while the board stays current.

**Tech Stack:** Python 3.11+, pytest, PyYAML. No new third-party dependencies.

Full design reference: `docs/superpowers/specs/2026-07-12-plan-work-review-resilience-design.md`

---

## Task 1: `escalate_issue` tool

**Files:**
- Create: `tools/escalate_issue.py`
- Test: `tests/test_escalate_issue.py`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_escalate_issue.py — Unit tests for tools/escalate_issue.py."""
from __future__ import annotations

from pathlib import Path

from tools.escalate_issue import EscalateIssueTool


class TestEscalateIssueTool:
    def test_writes_escalation_file_next_to_handoff(self, tmp_path):
        handoff_path = tmp_path / "worker_ab12cd34.md"
        tool = EscalateIssueTool(handoff_path=handoff_path)

        tool.run(question="Which auth library?", context="Plan doesn't specify.")

        escalation_path = tmp_path / "worker_ab12cd34_escalation.md"
        assert escalation_path.exists()

    def test_escalation_file_contains_question_and_context(self, tmp_path):
        handoff_path = tmp_path / "review_9f8e7d6c.md"
        tool = EscalateIssueTool(handoff_path=handoff_path)

        tool.run(question="Is 200 or 201 expected?", context="Test asserts 200, criteria says 201.")

        content = (tmp_path / "review_9f8e7d6c_escalation.md").read_text(encoding="utf-8")
        assert "Is 200 or 201 expected?" in content
        assert "Test asserts 200, criteria says 201." in content

    def test_creates_parent_dir_if_missing(self, tmp_path):
        handoff_path = tmp_path / "nested" / "dir" / "worker_1.md"
        tool = EscalateIssueTool(handoff_path=handoff_path)

        tool.run(question="q", context="c")

        assert (tmp_path / "nested" / "dir" / "worker_1_escalation.md").exists()

    def test_run_returns_end_turn_instruction(self, tmp_path):
        handoff_path = tmp_path / "worker_1.md"
        tool = EscalateIssueTool(handoff_path=handoff_path)

        result = tool.run(question="q", context="c")

        assert "end your turn" in result.lower()

    def test_schema_requires_question_and_context(self, tmp_path):
        tool = EscalateIssueTool(handoff_path=tmp_path / "worker_1.md")

        assert tool._parameters["required"] == ["question", "context"]
        assert tool.name == "escalate_issue"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_escalate_issue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.escalate_issue'`

- [ ] **Step 3: Write minimal implementation**

```python
"""tools/escalate_issue.py — Let a worker/review subagent raise a blocking issue to the main agent.

Writes a sidecar "<handoff-stem>_escalation.md" file next to the subagent's own
handoff path. tools/_subagent_runner.py polls for this file and, on finding it,
terminates the subagent subprocess and surfaces the escalation to the main agent
as a tool result (see tools/spawn_subagent.py). This is a fast-fail channel, not
live Q&A: the subagent's turn ends the moment it calls this tool.
"""
from __future__ import annotations

from pathlib import Path

from agent.base_tool import BaseTool


class EscalateIssueTool(BaseTool):
    """Write an escalation report next to the subagent's handoff file."""

    name = "escalate_issue"
    description = (
        "Raise a blocking question or issue to the main agent immediately, "
        "without waiting for your handoff report to be read. Use this when you "
        "hit an ambiguity, missing dependency, or blocker you cannot resolve on "
        "your own. After calling this tool, immediately end your turn — do not "
        "continue working."
    )

    _parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The specific question or blocking issue to raise to the main agent.",
            },
            "context": {
                "type": "string",
                "description": (
                    "Relevant context: what you were doing, what you tried, and "
                    "why you are blocked."
                ),
            },
        },
        "required": ["question", "context"],
    }

    def __init__(self, handoff_path: Path) -> None:
        self._handoff_path = Path(handoff_path)

    def run(self, question: str, context: str) -> str:
        escalation_path = self._handoff_path.with_name(
            self._handoff_path.stem + "_escalation.md"
        )
        escalation_path.parent.mkdir(parents=True, exist_ok=True)
        escalation_path.write_text(
            f"# Escalation\n\n## Question\n{question}\n\n## Context\n{context}\n",
            encoding="utf-8",
        )
        return (
            "Escalation recorded. End your turn now — do not continue working. "
            "The main agent will answer and, if needed, re-spawn you with guidance."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_escalate_issue.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/escalate_issue.py tests/test_escalate_issue.py
git commit -m "feat: add escalate_issue tool for worker/review subagents"
```

---

## Task 2: Escalation detection in `tools/_subagent_runner.py`

**Files:**
- Modify: `tools/_subagent_runner.py:58-88` (`_poll_until`)
- Test: `tests/test_subagent_runner.py`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_subagent_runner.py — Unit tests for tools/_subagent_runner.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from tools._subagent_runner import _poll_until, _SubagentState


def _make_state(tmp_path: Path, poll_side_effect) -> tuple[_SubagentState, MagicMock]:
    proc = MagicMock()
    proc.pid = 4242
    proc.poll.side_effect = poll_side_effect
    handoff_path = tmp_path / "worker_ab12cd34.md"
    state = _SubagentState(
        proc=proc,
        handoff_path=handoff_path,
        task_file=tmp_path / "task.txt",
        subagent_type="worker",
        on_event=None,
    )
    (tmp_path / "task.txt").write_text("task", encoding="utf-8")
    return state, proc


class TestEscalationDetection:
    def test_escalation_file_present_terminates_process_and_returns_escalated(self, tmp_path):
        escalation_path = tmp_path / "worker_ab12cd34_escalation.md"
        escalation_path.write_text(
            "# Escalation\n\n## Question\nWhich lib?\n\n## Context\nAmbiguous.\n",
            encoding="utf-8",
        )
        # Process never exits on its own — only the escalation check should end the poll.
        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)

        result = _poll_until(state, extra_seconds=10)

        assert result["status"] == "escalated"
        assert "Which lib?" in result["escalation"]
        proc.terminate.assert_called_once()

    def test_escalation_detected_even_when_process_still_alive_within_first_tick(self, tmp_path):
        escalation_path = tmp_path / "worker_ab12cd34_escalation.md"
        escalation_path.write_text("# Escalation\n\n## Question\nQ\n\n## Context\nC\n", encoding="utf-8")
        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)

        result = _poll_until(state, extra_seconds=1)

        assert result["status"] == "escalated"

    def test_no_escalation_file_falls_through_to_normal_ok_path(self, tmp_path):
        state, proc = _make_state(tmp_path, poll_side_effect=[None, 0])
        state.handoff_path.write_text("# Handoff\n\ndone\n", encoding="utf-8")

        result = _poll_until(state, extra_seconds=10)

        assert result["status"] == "ok"

    def test_malformed_escalation_file_returns_error_not_crash(self, tmp_path, monkeypatch):
        escalation_path = tmp_path / "worker_ab12cd34_escalation.md"
        escalation_path.write_bytes(b"\xff\xfe\x00\x01")  # invalid utf-8
        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)

        result = _poll_until(state, extra_seconds=10)

        assert result["status"] == "error"
        assert "escalation" in result["message"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_subagent_runner.py -v`
Expected: FAIL — `test_escalation_file_present_terminates_process_and_returns_escalated` and related
tests fail because `_poll_until` never checks for the escalation file (loops until `extra_seconds`
elapses, then returns `{"status": "timeout", ...}` instead of `{"status": "escalated", ...}`).

- [ ] **Step 3: Write minimal implementation**

Replace `_poll_until` in `tools/_subagent_runner.py:58-88` with:

```python
def _poll_until(
    state: _SubagentState,
    extra_seconds: float,
) -> dict:
    """Poll proc until it exits, escalates, or extra_seconds elapses.

    Returns:
        {"status": "ok",        "handoff": str}   — done, handoff written
        {"status": "escalated", "escalation": str} — subagent raised a blocking issue
        {"status": "timeout",   "pid": int}        — still alive, deadline expired
        {"status": "error",     "message": str}    — exited without writing handoff,
                                                      or escalation file unreadable
    """
    import time

    deadline = time.monotonic() + extra_seconds
    proc = state.proc
    escalation_path = state.handoff_path.with_name(
        state.handoff_path.stem + "_escalation.md"
    )

    while True:
        if escalation_path.exists():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            with _active_lock:
                _active.pop(proc.pid, None)
            state.task_file.unlink(missing_ok=True)
            try:
                content = escalation_path.read_text(encoding="utf-8")
            except OSError as exc:
                return {
                    "status": "error",
                    "message": f"escalation file present but unreadable: {exc}",
                }
            return {"status": "escalated", "escalation": content}

        ret = proc.poll()
        if ret is not None:
            with _active_lock:
                _active.pop(proc.pid, None)
            state.task_file.unlink(missing_ok=True)
            if state.handoff_path.exists():
                return {"status": "ok", "handoff": str(state.handoff_path)}
            return {
                "status": "error",
                "message": f"subagent exited (code {ret}) without writing handoff",
            }
        if time.monotonic() >= deadline:
            return {"status": "timeout", "pid": proc.pid}
        time.sleep(_POLL_INTERVAL)
```

Note: the escalation check runs *before* the exit check on every tick, so an escalation file
written right at process exit is still caught as `"escalated"` rather than falling through to the
`"ok"`/`"error"` exit path.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_subagent_runner.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Regression check — existing subagent runner behavior untouched**

Run: `conda run -n dagi python -m pytest tests/test_spawn_subagent_tool.py -v`
Expected: PASS (all existing tests still pass — `_poll_until`'s exit-path logic is unchanged for
the no-escalation case)

- [ ] **Step 6: Commit**

```bash
git add tools/_subagent_runner.py tests/test_subagent_runner.py
git commit -m "feat: detect escalation files in subagent poll loop, terminate on detection"
```

---

## Task 3: Surface escalation in `tools/spawn_subagent.py`

**Files:**
- Modify: `tools/spawn_subagent.py:174-190` (`SpawnSubagentTool.run`)
- Modify: `tests/test_spawn_subagent_tool.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_spawn_subagent_tool.py`, inside `class TestRunMethod:` (after
`test_run_returns_error_string_on_error`):

```python
    def test_run_returns_escalation_content_on_escalated_status(self, tmp_path):
        """run() surfaces the escalation question/context when status is 'escalated'."""
        config = _make_config(tmp_path)
        tool = _make_tool("worker", config, WORKER_SCHEMA)
        escalated_result = {
            "status": "escalated",
            "escalation": "# Escalation\n\n## Question\nWhich lib?\n\n## Context\nAmbiguous.\n",
        }

        with patch("tools._subagent_runner.run_subagent", return_value=escalated_result):
            result = tool.run(subtask_name="Do the thing")

        assert "escalated" in result.lower()
        assert "Which lib?" in result
        assert "Ambiguous." in result

    def test_run_escalated_works_for_review_type_too(self, tmp_path):
        """Escalated branch is not worker-specific — review subagents use it too."""
        config = _make_config(tmp_path)
        tool = _make_tool("review", config, REVIEW_SCHEMA)
        escalated_result = {
            "status": "escalated",
            "escalation": "# Escalation\n\n## Question\nExpected status code?\n\n## Context\nMismatch.\n",
        }

        with patch("tools._subagent_runner.run_subagent", return_value=escalated_result):
            result = tool.run(
                subtask_name="Do the thing",
                worker_handoff_path="/tmp/handoff.md",
                unit_test_paths=["tests/test_thing.py"],
            )

        assert "escalated" in result.lower()
        assert "Expected status code?" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_spawn_subagent_tool.py -v -k escalat`
Expected: FAIL — `result` currently falls through to the generic error branch (`"[worker error] ..."`
or similar), since `SpawnSubagentTool.run` has no `"escalated"` branch yet, so `"escalated"` does
not appear (lower-cased) in the returned string, and the question text is not surfaced verbatim.

- [ ] **Step 3: Write minimal implementation**

In `tools/spawn_subagent.py`, inside `SpawnSubagentTool.run` (currently lines 174-190), add the new
branch before the existing `if result["status"] == "ok":` check:

```python
        if self._tracker:
            self._tracker.record_subagent_end(subagent_id, str(result), depth)

        if result["status"] == "escalated":
            return f"[{self._type_name} escalated]\n\n{result['escalation']}"
        if result["status"] == "ok":
            return f"Subagent completed. Handoff written to: {result['handoff']}"
        if result["status"] == "timeout":
            return json.dumps({"status": "timeout", "pid": result["pid"]})
        return f"[{self._type_name} error] {result.get('message', 'unknown error')}"
```

(Only the new `if result["status"] == "escalated":` line and its return are added; the surrounding
lines are unchanged from the current file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_spawn_subagent_tool.py -v`
Expected: PASS (all tests, including the 2 new ones)

- [ ] **Step 5: Commit**

```bash
git add tools/spawn_subagent.py tests/test_spawn_subagent_tool.py
git commit -m "feat: surface escalated subagent status as a tool result"
```

---

## Task 4: Wire `escalate_issue` into the subagent's own tool registry

The `escalate_issue` tool needs to know its own subagent's `handoff_path` at construction time.
This requires threading `handoff_path` from `cli.py`'s pipe-mode runner through
`build_subagent_registry` down to `_tools_from_list`.

**Files:**
- Modify: `agent/tools.py:65-95` (`_tools_from_list`) and `agent/tools.py:400-462` (`build_subagent_registry`)
- Modify: `cli.py:1071-1146` (`_run_subagent_pipe_mode`)
- Modify: `.dagi/subagents/worker/subagent_config.yaml`
- Modify: `.dagi/subagents/review/subagent_config.yaml`
- Test: `tests/test_escalate_issue_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_escalate_issue_wiring.py — escalate_issue reaches subagent registries."""
from __future__ import annotations

from pathlib import Path

import yaml

from agent.tools import build_subagent_registry
from tools.escalate_issue import EscalateIssueTool


def _make_config(tmp_path: Path):
    from agent.loop import AgentConfig
    return AgentConfig(model="test-model", api_key="test-key", project_path=tmp_path)


class TestEscalateIssueWiring:
    def test_worker_registry_includes_escalate_issue_when_handoff_path_given(self, tmp_path):
        subagent_dir = tmp_path / ".dagi" / "subagents" / "worker"
        subagent_dir.mkdir(parents=True)
        (subagent_dir / "subagent_config.yaml").write_text(
            yaml.dump({"model_tier": "worker", "tools": ["read", "escalate_issue"]}),
            encoding="utf-8",
        )
        config = _make_config(tmp_path)
        handoff_path = tmp_path / "worker_ab12cd34.md"

        registry = build_subagent_registry(
            subagent_type="worker",
            config=config,
            project_path=tmp_path,
            handoff_path=handoff_path,
        )

        tool = registry._tools.get("escalate_issue")
        assert isinstance(tool, EscalateIssueTool)
        assert tool._handoff_path == handoff_path

    def test_registry_omits_escalate_issue_when_not_in_tools_list(self, tmp_path):
        subagent_dir = tmp_path / ".dagi" / "subagents" / "explore_files"
        subagent_dir.mkdir(parents=True)
        (subagent_dir / "subagent_config.yaml").write_text(
            yaml.dump({"model_tier": "worker", "tools": ["read"]}),
            encoding="utf-8",
        )
        config = _make_config(tmp_path)

        registry = build_subagent_registry(
            subagent_type="explore_files",
            config=config,
            project_path=tmp_path,
            handoff_path=tmp_path / "explore_1.md",
        )

        assert registry._tools.get("escalate_issue") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_escalate_issue_wiring.py -v`
Expected: FAIL — `build_subagent_registry() got an unexpected keyword argument 'handoff_path'`.

Note: `ToolRegistry` (in `agent/registry.py`) stores tools in a plain `self._tools: dict[str,
BaseTool]` with no public `get_tool()` accessor — the test above and Step 3 below both use
`registry._tools.get(...)` directly, which is the existing (if unencapsulated) way this codebase's
own tests reach into a registry's contents.

- [ ] **Step 3: Write minimal implementation**

In `agent/tools.py`, modify `_tools_from_list` (currently lines 65-95) to accept an optional
`handoff_path` and register `escalate_issue` when requested:

```python
def _tools_from_list(
    tool_names: list[str],
    cwd: Path,
    allowed_roots: list[Path] | None,
    handoff_path: Path | None = None,
) -> list[BaseTool]:
    """Instantiate tools by name for a subagent registry."""
    from tools.web_fetch import WebFetchTool
    from tools.web_search import WebSearchTool
    from tools.escalate_issue import EscalateIssueTool

    registry_map: dict[str, BaseTool] = {
        "read":       ReadTool(cwd=cwd, allowed_roots=allowed_roots),
        "grep":       GrepTool(cwd=cwd, allowed_roots=allowed_roots),
        "find":       FindTool(cwd=cwd, allowed_roots=allowed_roots),
        "write":      WriteTool(cwd=cwd, allowed_roots=allowed_roots),
        "edit":       EditTool(cwd=cwd, allowed_roots=allowed_roots),
        "copy":       CopyTool(cwd=cwd, allowed_roots=allowed_roots),
        "bash":       BashTool(cwd=cwd),
        "web_search": WebSearchTool(),
        "web_fetch":  WebFetchTool(),
    }
    if handoff_path is not None:
        registry_map["escalate_issue"] = EscalateIssueTool(handoff_path=handoff_path)
    result: list[BaseTool] = []
    for name in tool_names:
        tool = registry_map.get(name)
        if tool is not None:
            result.append(tool)
        else:
            print(
                f"[tools] Warning: unknown tool name {name!r} in subagent_config.yaml",
                file=sys.stderr,
            )
    return result
```

Then modify `build_subagent_registry` (currently lines 400-462) to accept and thread through
`handoff_path`:

```python
def build_subagent_registry(
    subagent_type: str,
    config: "AgentConfig",
    project_path: Path,
    plan_file: Path | None = None,
    callbacks: "AgentCallbacks | None" = None,
    tracker: "SessionTracker | None" = None,
    memory_root: Path | None = None,
    handoff_path: Path | None = None,
) -> ToolRegistry:
```

(only the new `handoff_path: Path | None = None` parameter is added to the signature; the docstring
gains one line: `handoff_path:  Path where this subagent must write its handoff report; threaded to`
`               escalate_issue so it knows where to write its sidecar escalation file.`)

And update both call sites inside the function body that call `_tools_from_list`:

```python
    if subagent_type == "custom":
        for tool in _tools_from_list(
            ["read", "grep", "find", "write", "edit", "bash", "web_search", "web_fetch"],
            project_path, default_roots, handoff_path=handoff_path,
        ):
            reg.register(tool)
        return reg
```

```python
    for tool in _tools_from_list(tool_names, cwd_for_tools, effective_roots, handoff_path=handoff_path):
        reg.register(tool)
    return reg
```

Finally, in `cli.py`'s `_run_subagent_pipe_mode` (currently lines 1071-1146), pass `handoff_path`
through to `build_subagent_registry`:

```python
    registry = build_subagent_registry(
        subagent_type=subagent_type,
        config=typed_config,
        project_path=project_path,
        callbacks=callbacks,
        memory_root=typed_config.memory_root,
        handoff_path=handoff_path,
    )
```

(only the new `handoff_path=handoff_path,` line is added; `handoff_path` is already a local
variable earlier in the function via `handoff_path = Path(handoff)`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_escalate_issue_wiring.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Regression check**

Run: `conda run -n dagi python -m pytest tests/test_git_tools_registration.py tests/test_spawn_subagent_tool.py -v`
Expected: PASS — confirms `build_subagent_registry`'s new optional parameter didn't break existing
callers (all other call sites omit `handoff_path`, which defaults to `None`, preserving prior
behavior).

- [ ] **Step 6: Add `escalate_issue` to worker and review tool lists**

Edit `.dagi/subagents/worker/subagent_config.yaml` — change the `tools:` list from:

```yaml
tools:
  - read
  - grep
  - find
  - write
  - edit
  - copy
  - bash
  - web_search
  - web_fetch
```

to:

```yaml
tools:
  - read
  - grep
  - find
  - write
  - edit
  - copy
  - bash
  - web_search
  - web_fetch
  - escalate_issue
```

Edit `.dagi/subagents/review/subagent_config.yaml` — change the `tools:` list from:

```yaml
tools:
  - read
  - grep
  - find
  - bash
```

to:

```yaml
tools:
  - read
  - grep
  - find
  - bash
  - escalate_issue
```

- [ ] **Step 7: Commit**

```bash
git add agent/tools.py cli.py tests/test_escalate_issue_wiring.py \
  .dagi/subagents/worker/subagent_config.yaml .dagi/subagents/review/subagent_config.yaml
git commit -m "feat: wire escalate_issue into worker/review subagent registries"
```

---

## Task 5: Update worker and review subagent prompts

**Files:**
- Modify: `.dagi/subagents/worker/prompt.md`
- Modify: `.dagi/subagents/review/prompt.md`

- [ ] **Step 1: Add escalation instructions to the worker prompt**

Edit `.dagi/subagents/worker/prompt.md`. In the `## Guidelines` section, replace the last bullet:

```markdown
- If you encounter a blocker you cannot resolve, document it clearly in the handoff report rather than stopping silently
```

with:

```markdown
- If you encounter a blocking ambiguity or issue you cannot resolve on your own (missing
  requirement detail, contradictory instructions, a dependency that doesn't exist), call
  `escalate_issue(question=..., context=...)` immediately — do not guess and do not keep working.
  **After calling `escalate_issue`, immediately end your turn.** Do not write a handoff report in
  this case; the escalation is handled separately by the main agent, which will re-spawn you with
  an answer.
- For anything else, document blockers clearly in the handoff report rather than stopping silently.
```

- [ ] **Step 2: Add escalation instructions to the review prompt**

Edit `.dagi/subagents/review/prompt.md`. In the `## Guidelines` section, add a new bullet after
the "Be actionable" bullet:

```markdown
- If you encounter a blocking ambiguity you cannot resolve (e.g. the acceptance criteria and the
  test file contradict each other, or a referenced file/handoff path doesn't exist), call
  `escalate_issue(question=..., context=...)` immediately — do not guess a verdict. **After calling
  `escalate_issue`, immediately end your turn** rather than writing a review report; the main agent
  will re-spawn you with an answer.
```

- [ ] **Step 3: Verify the prompts read correctly**

Run: `conda run -n dagi python -c "print(open('.dagi/subagents/worker/prompt.md', encoding='utf-8').read())"`
Run: `conda run -n dagi python -c "print(open('.dagi/subagents/review/prompt.md', encoding='utf-8').read())"`
Expected: both print with the new escalation guidance present in the `## Guidelines` section, no
markdown formatting errors (headings/bullets render correctly).

- [ ] **Step 4: Commit**

```bash
git add .dagi/subagents/worker/prompt.md .dagi/subagents/review/prompt.md
git commit -m "docs: add escalate_issue guidance to worker/review subagent prompts"
```

---

## Task 6: Live plan status board — rendering and prefix caching

**Files:**
- Modify: `agent/loop.py:788-866` (`_build_preamble`, `_assemble_system_string`)
- Test: `tests/test_plan_status_board.py`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_plan_status_board.py — Live plan status board rendering + prefix caching."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.loop import AgentConfig, AgentLoop


def _make_loop(project_path: Path, active_plan_file: str | None = None) -> AgentLoop:
    config = AgentConfig(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        project_path=project_path,
        active_plan_file=active_plan_file,
    )

    fake_registry = MagicMock()
    fake_registry.get_openai_tools_list.return_value = []
    fake_registry.list_tools.return_value = []

    fake_tracker = MagicMock()
    fake_tracker.record_system = MagicMock()
    fake_tracker.record_user = MagicMock()
    fake_tracker.record_assistant = MagicMock()

    with (
        patch("agent.loop.SessionTracker", return_value=fake_tracker),
        patch("openai.OpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        loop = AgentLoop(config=config, _registry=fake_registry, _tracker=fake_tracker)

    loop.tracker = fake_tracker
    loop.registry = fake_registry
    return loop


PLAN_TEXT = """\
# Plan: Test Feature

## Subtasks

### Subtask 1: [x] Add escalate_issue tool
**Goal:** Done.

### Subtask 2: [~] Wire runner escalation detection
**Goal:** In progress.

### Subtask 3: [ ] Update plan-work-review skill
**Goal:** Pending.

### Subtask 4: [!] Add status board renderer
**Goal:** Failed once.
"""


class TestPlanStatusBoardRendering:
    def test_status_board_lists_all_subtasks_with_markers(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        tail = loop._build_active_plan_tail()

        assert "## Plan Status" in tail
        assert "[x] Add escalate_issue tool" in tail
        assert "[~] Wire runner escalation detection" in tail
        assert "[ ] Update plan-work-review skill" in tail
        assert "[!] Add status board renderer" in tail

    def test_no_active_plan_returns_empty_tail(self, tmp_path):
        loop = _make_loop(tmp_path, active_plan_file=None)

        assert loop._build_active_plan_tail() == ""

    def test_plan_mode_active_returns_empty_tail(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))
        loop.config.plan_mode = True

        assert loop._build_active_plan_tail() == ""

    def test_malformed_plan_file_does_not_raise(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("not a real plan, no headings at all", encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        tail = loop._build_active_plan_tail()

        assert "## Active Plan" in tail  # pointer section still renders

    def test_missing_plan_file_does_not_raise(self, tmp_path):
        loop = _make_loop(tmp_path, active_plan_file=str(tmp_path / "does_not_exist.md"))

        tail = loop._build_active_plan_tail()

        assert "## Active Plan" in tail


class TestSystemPrefixCaching:
    def test_system_prefix_set_after_init(self, tmp_path):
        loop = _make_loop(tmp_path, active_plan_file=None)

        assert isinstance(loop._system_prefix, str)
        assert len(loop._system_prefix) > 0

    def test_system_prefix_excludes_active_plan_tail(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        assert "## Active Plan" not in loop._system_prefix
        assert "## Plan Status" not in loop._system_prefix

    def test_full_system_string_equals_prefix_plus_tail(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        full = loop._messages[0]["content"]
        assert full == loop._system_prefix + loop._build_active_plan_tail()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_plan_status_board.py -v`
Expected: FAIL with `AttributeError: 'AgentLoop' object has no attribute '_build_active_plan_tail'`
and `AttributeError: 'AgentLoop' object has no attribute '_system_prefix'`

- [ ] **Step 3: Write minimal implementation**

In `agent/loop.py`, replace the tail of `_assemble_system_string` (currently lines 844-866) — i.e.
everything from `preamble = self._build_preamble(dagi_root)` through the final `return system` —
with:

```python
        preamble = self._build_preamble(dagi_root)
        sections = [s for s in [preamble, prompt] if s]
        system = "\n\n---\n\n".join(sections)
        system += f"\n\n---\n\nProject root: {self.config.project_path}"

        self._system_prefix = system
        return system + self._build_active_plan_tail()

    def _build_active_plan_tail(self) -> str:
        """Build the '## Active Plan' + live status board tail.

        Returns an empty string when no plan is active (or plan mode is active,
        in which case the plan file is being edited directly and doesn't need
        this reminder). Called both at system-string assembly time and, every
        loop iteration, by _refresh_active_plan_tail() to keep the status board
        current without rebuilding the (cache-relevant) prefix.
        """
        if not (self.config.active_plan_file and not self.config.plan_mode):
            return ""

        tail = (
            f"\n\n---\n\n"
            f"## Active Plan\n\n"
            f"A plan document is active at: `{self.config.active_plan_file}`\n\n"
            f"**Before starting any implementation work**, read the plan file "
            f"in full — it contains both the subtask definitions and the "
            f"execution protocol you must follow.\n\n"
            f"As you work:\n"
            f"- Follow the **Execution Protocol** section in the plan exactly.\n"
            f"- After completing each subtask, edit the plan and update its "
            f"status marker.\n"
            f"- If something feels wrong or unclear, re-read the plan file — "
            f"the answer is likely there.\n"
            f"- If you deviate from the plan, update it to reflect reality."
        )
        tail += self._render_plan_status_section()
        return tail

    def _render_plan_status_section(self) -> str:
        """Render the '## Plan Status' board from the active plan file's subtask markers."""
        from tools._plan_parser import parse_subtask_statuses

        try:
            plan_text = Path(self.config.active_plan_file).read_text(encoding="utf-8")
        except OSError:
            return ""

        statuses = parse_subtask_statuses(plan_text)
        if not statuses:
            return ""

        marker_map = {
            "pending": " ", "in_progress": "~", "complete": "x",
            "failed": "!", "unknown": "?",
        }
        lines = [
            f"{i}. [{marker_map.get(s['status'], '?')}] {s['name']}"
            for i, s in enumerate(statuses, start=1)
        ]
        return "\n\n## Plan Status\n" + "\n".join(lines)

    def _refresh_active_plan_tail(self) -> None:
        """Re-splice the Active Plan + Plan Status tail onto the cached prefix.

        Called at the top of every loop iteration in run(). Cheap: one file read
        + one regex parse. Never touches self._system_prefix, so cache_prompt's
        hit rate on the large static prefix is unaffected.
        """
        if self.config.active_plan_file and not self.config.plan_mode:
            self._messages[0] = {
                "role": "system",
                "content": self._system_prefix + self._build_active_plan_tail(),
            }
```

Note: `Path` is already imported at the top of `agent/loop.py` (used elsewhere in the file for
`plan_file: Path`, `dagi_root: Path` parameters), so no new import is needed for
`_render_plan_status_section`.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_plan_status_board.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Regression check**

Run: `conda run -n dagi python -m pytest tests/test_plan_mode_branch.py tests/test_git_branch.py -v`
Expected: PASS — confirms `_assemble_system_string`'s public return value (the full string) is
unchanged for existing callers; only its internal structure (now split into prefix + tail via two
new helper methods) changed.

- [ ] **Step 6: Commit**

```bash
git add agent/loop.py tests/test_plan_status_board.py
git commit -m "feat: render live plan status board, cache system-prompt prefix separately"
```

---

## Task 7: Per-iteration refresh in `AgentLoop.run()`

**Files:**
- Modify: `agent/loop.py:363-383` (`run`, top of main loop)
- Test: `tests/test_plan_status_board.py` (add a class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plan_status_board.py`:

```python
class TestPerIterationRefresh:
    def test_status_board_reflects_change_between_iterations(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        loop._refresh_active_plan_tail()
        assert "[~] Wire runner escalation detection" in loop._messages[0]["content"]

        # Simulate the subtask completing between iterations.
        plan_file.write_text(
            PLAN_TEXT.replace(
                "### Subtask 2: [~] Wire runner escalation detection",
                "### Subtask 2: [x] Wire runner escalation detection",
            ),
            encoding="utf-8",
        )
        loop._refresh_active_plan_tail()

        assert "[x] Wire runner escalation detection" in loop._messages[0]["content"]
        assert "[~] Wire runner escalation detection" not in loop._messages[0]["content"]

    def test_prefix_unchanged_across_refreshes(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))
        prefix_before = loop._system_prefix

        plan_file.write_text(PLAN_TEXT.replace("[~]", "[x]"), encoding="utf-8")
        loop._refresh_active_plan_tail()

        assert loop._system_prefix == prefix_before

    def test_no_active_plan_refresh_is_a_no_op(self, tmp_path):
        loop = _make_loop(tmp_path, active_plan_file=None)
        content_before = loop._messages[0]["content"]

        loop._refresh_active_plan_tail()

        assert loop._messages[0]["content"] == content_before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_plan_status_board.py::TestPerIterationRefresh -v`
Expected: These should actually already PASS once Task 6 is done, since `_refresh_active_plan_tail`
was implemented there — this step exists to confirm the refresh method behaves correctly under
direct invocation before wiring it into `run()`'s loop. If any of these three fail, fix
`_refresh_active_plan_tail` (from Task 6) before proceeding — do not add the `run()` call site on
top of a broken refresh method.

- [ ] **Step 3: Wire the refresh into the main loop**

In `agent/loop.py`, inside `run()` (currently lines 363-383), change:

```python
        try:
            iteration = 0
            while True:
                iteration += 1
                self.callbacks.on_iteration(iteration)
                self._pause_event.wait()  # blocks here when paused; instant no-op otherwise
```

to:

```python
        try:
            iteration = 0
            while True:
                iteration += 1
                self._refresh_active_plan_tail()
                self.callbacks.on_iteration(iteration)
                self._pause_event.wait()  # blocks here when paused; instant no-op otherwise
```

- [ ] **Step 4: Run the full plan-status test suite to verify integration**

Run: `conda run -n dagi python -m pytest tests/test_plan_status_board.py -v`
Expected: PASS (11 tests total across both classes)

- [ ] **Step 5: Full regression run**

Run: `conda run -n dagi python -m pytest tests/ -v`
Expected: PASS — full suite green, confirming the new per-iteration refresh call doesn't break
continuation handling (`tests/test_continuation.py`), compaction, or any other loop-level test.

- [ ] **Step 6: Commit**

```bash
git add agent/loop.py tests/test_plan_status_board.py
git commit -m "feat: refresh live plan status board at the top of every loop iteration"
```

---

## Task 8: Update `plan-work-review` skill — escalation branch + retry budget

**Files:**
- Modify: `.dagi/skills/plan-work-review/SKILL.md`

- [ ] **Step 1: Add the ESCALATED branch to Phase 2 Step 4**

In `.dagi/skills/plan-work-review/SKILL.md`, in `### Step 4 — Evaluate and Decide`, insert a new
branch before `**If PASS:**`:

```markdown
### Step 4 — Evaluate and Decide
Read the review report. Pass/fail is determined by the review subagent's verdict — not your own
judgment.

**If ESCALATED:** The worker or review subagent raised a blocking question instead of producing a
handoff/review report (the tool result starts with `[worker escalated]` or `[review escalated]`).
- Read the question and context in full.
- Decide the answer yourself if you can — you have full repo access and the plan/conversation
  context the subagent doesn't. Only call `ask_user` if it's a genuine judgment call the user must
  make (e.g. a product decision, not a technical detail you can look up or infer).
- Re-spawn the **same subagent type** for the **same subtask**, passing the answer via
  `custom_instructions` (e.g. `"custom_instructions": "Answering your escalation: use bcrypt, not argon2, per existing auth.py conventions."`).
- **This does not consume a retry attempt.** Escalations are free — do not increment your attempt
  count for this subtask. Go back to Step 2 (or Step 3, if it was the review subagent that
  escalated) with the same attempt number as before.

**If PASS:**
```

- [ ] **Step 2: Change the retry budget language**

In the same section, change:

```markdown
**If 3 attempts are exhausted without PASS:**
```

to:

```markdown
**If 2 attempts are exhausted without PASS** (1 initial attempt + 1 retry — escalations are free
and do not count toward this budget):
```

- [ ] **Step 3: Update the frontmatter description to match**

Change the frontmatter `description:` field (currently ending "...then executes it via worker and
review subagents with retry logic.") — no change needed here, the wording is already generic
enough to cover the updated retry count. Skip this step if no frontmatter text mentions "3" or
"three" explicitly.

Run: `conda run -n dagi python -c "print('3 attempts' in open('.dagi/skills/plan-work-review/SKILL.md', encoding='utf-8').read())"`
Expected: prints `False` (confirms no stale "3 attempts" reference remains anywhere in the file)

- [ ] **Step 4: Commit**

```bash
git add .dagi/skills/plan-work-review/SKILL.md
git commit -m "docs: add ESCALATED branch and reduce retry budget to 2 attempts in plan-work-review skill"
```

---

## Task 9: End-to-end sanity check

**Files:** none modified — verification only

- [ ] **Step 1: Run the full test suite**

Run: `conda run -n dagi python -m pytest tests/ -v`
Expected: PASS, 0 failures

- [ ] **Step 2: Manual smoke test of the escalation path**

Run a quick manual check that a worker subagent calling `escalate_issue` actually surfaces through
`spawn_worker_subagent`:

```bash
conda run -n dagi python -c "
from pathlib import Path
from tools.escalate_issue import EscalateIssueTool

handoff = Path('/tmp/dagi_smoke_test/worker_smoketest.md')
tool = EscalateIssueTool(handoff_path=handoff)
print(tool.run(question='Smoke test question', context='Smoke test context'))
print((handoff.parent / 'worker_smoketest_escalation.md').read_text(encoding='utf-8'))
"
```

Expected output: the end-your-turn confirmation message, followed by the escalation file's
contents showing the question and context rendered correctly.

- [ ] **Step 3: Update project docs**

Invoke the `update-project-context` skill to record this feature in `PROJECT_CONTEXT.md` (new
architecture note on the escalation channel + live status board, plus an entry in the
"Claude's Insights" section if anything non-obvious surfaced during implementation).

Update `TODO.md` and `README.md` per `CLAUDE.local.md`'s standing instruction to keep them current
with the actual state of the repo.

- [ ] **Step 4: Final commit**

```bash
git add PROJECT_CONTEXT.md TODO.md README.md
git commit -m "docs: update project context and TODO for plan-work-review resilience feature"
```
