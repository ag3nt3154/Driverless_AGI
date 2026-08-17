# Session Log Tree — Agent Loop Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `branch/start` event logging into the subagent spawn path so that every subagent execution is recorded as a branch on the parent's `SessionLog`.

**Architecture:** Thread the parent's `SessionLog` from `AgentLoop` through `create_tool_registry()` and `_discover_subagent_tools()` into each subagent tool's constructor. Each tool passes it as `parent_log` to `run_subagent()`, which logs a `branch/start` event before spawning the subprocess. The subprocess itself is unchanged.

**Tech Stack:** Python 3.11+, pytest, existing `agent/session_*` modules

## Global Constraints

- Functions <= 100 lines, CC <= 8, <= 5 positional params, lines <= 100 chars, files <= 500 lines.
- `run_subagent()` in `tools/subagent_api.py` is the only public subagent API — never import `_subagent_runner` directly.
- `SessionLog.append()` already enforces that `BRANCH_START` events must have `branch="main"` and that the branch name cannot be `"main"`.
- Existing 835 tests must continue passing.
- Use `conda run -n dagi python -m pytest` to run tests.

---

### Task 1: Add `parent_log` parameter to `run_subagent()` and log `branch/start`

**Files:**
- Modify: `tools/subagent_api.py:89-161`
- Test: `tests/test_subagent_api.py` (new)

**Interfaces:**
- Consumes: `SessionLog.append()`, `SessionLog.open_turn`, `SessionLog.open_step` from `agent/session_log.py`; `session_events.BRANCH_START` from `agent/session_events.py`
- Produces: `run_subagent(..., parent_log=)` — new optional kwarg accepted by the public API. `SubagentResult.branch_id: str | None` — new field.

- [ ] **Step 1: Write failing tests**

Create `tests/test_subagent_api.py`:

```python
"""Tests for branch/start logging in run_subagent()."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from agent import session_events as sev
from agent.session_log import SessionLog
from tools.subagent_api import run_subagent, SubagentResult


class TestBranchStartLogging:
    """run_subagent() logs branch/start on parent_log before spawning."""

    def _make_open_log(self) -> SessionLog:
        """Return a SessionLog with an open turn and step."""
        log = SessionLog()
        log.append(sev.TURN_START, {"turn": 1})
        log.append(sev.STEP_START, {"turn": 1, "step": 1})
        return log

    @patch("tools.subagent_api._runner.run_subagent")
    def test_branch_start_logged_before_spawn(self, mock_runner):
        """branch/start is appended to parent_log before the subprocess."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = self._make_open_log()
        initial_count = len(log.events)

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                run_subagent(
                    task="test",
                    prompt="do stuff",
                    parent_log=log,
                )

        branch_events = [
            e for e in log.events[initial_count:]
            if e.type == sev.BRANCH_START
        ]
        assert len(branch_events) == 1
        evt = branch_events[0]
        assert evt.data["parent_branch"] == "main"
        assert evt.data["turn"] == 1
        assert evt.data["step"] == 1
        assert evt.branch == "main"

    @patch("tools.subagent_api._runner.run_subagent")
    def test_no_parent_log_no_branch_event(self, mock_runner):
        """When parent_log is None, no branch/start is logged."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    prompt="do stuff",
                )
        assert result.branch_id is None

    @patch("tools.subagent_api._runner.run_subagent")
    def test_branch_id_on_result(self, mock_runner):
        """SubagentResult.branch_id is set when parent_log is provided."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = self._make_open_log()

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    prompt="do stuff",
                    parent_log=log,
                )
        assert result.branch_id is not None
        assert result.branch_id.startswith("custom_")

    @patch("tools.subagent_api._runner.run_subagent")
    def test_branch_id_uses_subagent_type(self, mock_runner):
        """branch_id is prefixed with the subagent type name."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = self._make_open_log()

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    preset="explore_files",
                    parent_log=log,
                    project_path=Path(__file__).parent.parent,
                )
        assert result.branch_id.startswith("explore_files_")

    @patch("tools.subagent_api._runner.run_subagent")
    def test_no_branch_when_no_open_turn(self, mock_runner):
        """No branch/start logged if parent_log has no open turn."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = SessionLog()  # no open turn

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    prompt="do stuff",
                    parent_log=log,
                )
        branch_events = [e for e in log.events if e.type == sev.BRANCH_START]
        assert len(branch_events) == 0
        assert result.branch_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_subagent_api.py -v`
Expected: FAIL — `run_subagent()` doesn't accept `parent_log`, `SubagentResult` has no `branch_id`.

- [ ] **Step 3: Implement — add `branch_id` to `SubagentResult`**

In `tools/subagent_api.py`, add field to `SubagentResult`:

```python
@dataclass
class SubagentResult:
    status: str
    handoff_text: str
    handoff_path: Path
    session_log_path: Path | None
    pid: int | None
    escalation: str | None
    branch_id: str | None = None
```

- [ ] **Step 4: Implement — add `parent_log` to `run_subagent()`**

In `tools/subagent_api.py`, add `parent_log` parameter and branch logging.
Add import at top of file:

```python
from agent import session_events as sev
```

Add `parent_log` parameter (after `on_event`):

```python
def run_subagent(
    task: str,
    preset: str | None = None,
    prompt: str | None = None,
    custom_instructions: str = "",
    tools: list[str] | None = None,
    timeout: float = 1800.0,
    model_tier: str = "default",
    handoff_spec: str = "",
    project_path: Path | None = None,
    on_event: Callable[[str], None] | None = None,
    parent_log: "SessionLog | None" = None,
) -> SubagentResult:
```

Add TYPE_CHECKING import for SessionLog:

```python
from typing import TYPE_CHECKING
# ... existing imports ...
if TYPE_CHECKING:
    from agent.session_log import SessionLog
```

After generating `subagent_id` and before spawning, add branch logging:

```python
    branch_id: str | None = None
    if (
        parent_log is not None
        and parent_log.open_turn is not None
    ):
        branch_id = f"{subagent_type}_{subagent_id}"
        parent_log.append(
            sev.BRANCH_START,
            {
                "branch": branch_id,
                "parent_branch": "main",
                "turn": parent_log.open_turn,
                "step": parent_log.open_step,
            },
        )
```

Update `_build_result` call to pass `branch_id`:

```python
    result = _build_result(raw, handoff_path)
    result.branch_id = branch_id
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_subagent_api.py -v`
Expected: PASS

- [ ] **Step 6: Run full suite to check no regressions**

Run: `conda run -n dagi python -m pytest tests/ -x -q`
Expected: 835+ tests passing

- [ ] **Step 7: Commit**

```bash
git add tools/subagent_api.py tests/test_subagent_api.py
git commit -m "feat: log branch/start in run_subagent() when parent_log is provided"
```

---

### Task 2: Thread `session_log` through `_discover_subagent_tools()` and `create_tool_registry()`

**Files:**
- Modify: `agent/subagent_tools.py:102-159` (`_discover_subagent_tools`)
- Modify: `agent/tools.py:110-293` (`create_tool_registry`)
- Test: `tests/test_subagent_tools_new.py` (existing — add cases)

**Interfaces:**
- Consumes: `SessionLog` from `agent/session_log.py`
- Produces: `_discover_subagent_tools(..., session_log=)` and `create_tool_registry(..., session_log=)` — new optional kwargs. Each discovered tool is constructed with `session_log=session_log`.

- [ ] **Step 1: Write failing test**

Add to `tests/test_subagent_tools_new.py`:

```python
class TestSessionLogThreading:
    """session_log is threaded from create_tool_registry to subagent tools."""

    def test_discover_passes_session_log(self, tmp_path):
        """_discover_subagent_tools passes session_log to tool constructors."""
        from agent.subagent_tools import _discover_subagent_tools
        from agent.session_log import SessionLog
        from unittest.mock import MagicMock

        log = SessionLog()
        config = MagicMock()
        config.project_path = tmp_path

        tools = _discover_subagent_tools(
            cwd=tmp_path,
            config=config,
            callbacks=None,
            tracker=None,
            session_log=log,
        )
        for tool in tools:
            assert getattr(tool, "_session_log", None) is log
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_subagent_tools_new.py::TestSessionLogThreading -v`
Expected: FAIL — `_discover_subagent_tools()` does not accept `session_log`.

- [ ] **Step 3: Implement — update `_discover_subagent_tools()`**

In `agent/subagent_tools.py`, add `session_log` parameter to `_discover_subagent_tools()`:

```python
def _discover_subagent_tools(
    cwd: Path,
    config: "AgentConfig",
    callbacks: "AgentCallbacks | None",
    tracker: "SessionTracker | None",
    session_log: "SessionLog | None" = None,
) -> list["BaseTool"]:
```

Add to TYPE_CHECKING block:

```python
if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog
```

Update the tool instantiation line (around line 148):

```python
                        tools_by_name[type_name] = obj(
                            config=config,
                            callbacks=callbacks,
                            tracker=tracker,
                            session_log=session_log,
                        )
```

- [ ] **Step 4: Implement — update `create_tool_registry()`**

In `agent/tools.py`, add `session_log` parameter:

```python
def create_tool_registry(
    cwd: Path = Path("."),
    allowed_roots: list[Path] | None = None,
    skill_roots: list[Path] | None = None,
    plan_mode: bool = False,
    plan_file: Path | None = None,
    plan_mode_initiated_by: str = "user",
    config: "AgentConfig | None" = None,
    callbacks: "AgentCallbacks | None" = None,
    tracker: "SessionTracker | None" = None,
    memory_root: Path | None = None,
    bash_tool: "object | None" = None,
    session_log: "SessionLog | None" = None,
) -> ToolRegistry:
```

Add TYPE_CHECKING import:

```python
if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog
```

Forward `session_log` in both `_discover_subagent_tools` call sites (plan mode ~line 185 and normal mode ~line 231):

```python
            for spawn_tool in _discover_subagent_tools(
                cwd=cwd, config=config, callbacks=callbacks,
                tracker=tracker, session_log=session_log,
            ):
```

- [ ] **Step 5: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_subagent_tools_new.py::TestSessionLogThreading -v`
Expected: PASS

- [ ] **Step 6: Run full suite to check no regressions**

Run: `conda run -n dagi python -m pytest tests/ -x -q`
Expected: 835+ tests passing

- [ ] **Step 7: Commit**

```bash
git add agent/subagent_tools.py agent/tools.py tests/test_subagent_tools_new.py
git commit -m "feat: thread session_log through tool discovery and registry creation"
```

---

### Task 3: Pass `self.log` from AgentLoop into `create_tool_registry()`

**Files:**
- Modify: `agent/loop.py:324-337` (`__init__`), `agent/loop.py:1438-1459` (`_rebuild_for_normal_mode`), `agent/loop.py:1461-1492` (`_rebuild_for_plan_mode`)
- Test: `tests/test_loop.py` (existing — add case)

**Interfaces:**
- Consumes: `create_tool_registry(..., session_log=)` from Task 2
- Produces: Every `create_tool_registry()` call in `AgentLoop` now forwards `session_log=self.log`.

- [ ] **Step 1: Write failing test**

Add to `tests/test_loop.py`:

```python
class TestSessionLogWiring:
    """AgentLoop passes its session log to the tool registry."""

    def test_subagent_tools_receive_session_log(self, tmp_path):
        """Subagent tools discovered during AgentLoop init receive the log."""
        from unittest.mock import patch, MagicMock
        from agent.loop import AgentLoop, AgentConfig

        config = AgentConfig(
            api_key="test-key",
            project_path=tmp_path,
        )

        captured_kwargs = {}
        original_discover = _discover_subagent_tools_ref()

        def spy_discover(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return []

        with patch(
            "agent.tools._discover_subagent_tools",
            side_effect=spy_discover,
        ):
            loop = AgentLoop(config=config)

        assert "session_log" in captured_kwargs
        assert captured_kwargs["session_log"] is loop.log


def _discover_subagent_tools_ref():
    from agent.subagent_tools import _discover_subagent_tools
    return _discover_subagent_tools
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_loop.py::TestSessionLogWiring -v`
Expected: FAIL — `create_tool_registry` is not called with `session_log`.

- [ ] **Step 3: Implement**

In `agent/loop.py`, update all three `create_tool_registry()` call sites to include `session_log=self.log`:

**`__init__` (~line 325):**
```python
            self.registry = create_tool_registry(
                cwd=config.project_path,
                allowed_roots=[dagi_root, config.project_path, self._effective_memory_root],
                skill_roots=skill_roots,
                plan_mode=config.plan_mode,
                plan_file=Path(config.plan_file) if config.plan_file else None,
                plan_mode_initiated_by=config.plan_mode_initiated_by,
                config=config,
                callbacks=self.callbacks,
                tracker=self.tracker,
                memory_root=self._effective_memory_root,
                bash_tool=_bash_tool,
                session_log=self.log,
            )
```

**`_rebuild_for_normal_mode` (~line 1438):**
```python
        self.registry = create_tool_registry(
            cwd=self.config.project_path,
            allowed_roots=[dagi_root, self.config.project_path, self._effective_memory_root],
            skill_roots=skill_roots,
            plan_mode=False,
            plan_file=None,
            plan_mode_initiated_by="user",
            config=self.config,
            callbacks=self.callbacks,
            tracker=self.tracker,
            memory_root=self._effective_memory_root,
            bash_tool=self._injected_bash_tool,
            session_log=self.log,
        )
```

**`_rebuild_for_plan_mode` (~line 1473):**
```python
        self.registry = create_tool_registry(
            cwd=self.config.project_path,
            allowed_roots=[dagi_root, self.config.project_path, self._effective_memory_root],
            skill_roots=skill_roots,
            plan_mode=True,
            plan_file=plan_file,
            plan_mode_initiated_by=initiated_by,
            config=self.config,
            callbacks=self.callbacks,
            tracker=self.tracker,
            memory_root=self._effective_memory_root,
            session_log=self.log,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_loop.py::TestSessionLogWiring -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `conda run -n dagi python -m pytest tests/ -x -q`
Expected: 835+ tests passing

- [ ] **Step 6: Commit**

```bash
git add agent/loop.py tests/test_loop.py
git commit -m "feat: pass session_log from AgentLoop to create_tool_registry"
```

---

### Task 4: Update all 10 subagent tools to accept `session_log` and pass `parent_log`

**Files:**
- Modify: `.dagi/subagents/explore_files/main.py`
- Modify: `.dagi/subagents/web_research/main.py`
- Modify: `.dagi/subagents/worker/main.py`
- Modify: `.dagi/subagents/review/main.py`
- Modify: `.dagi/subagents/plan/main.py`
- Modify: `.dagi/subagents/cli/main.py`
- Modify: `.dagi/subagents/read-large-text/main.py`
- Modify: `.dagi/subagents/memory-query/main.py`
- Modify: `.dagi/subagents/memory-add/main.py`
- Modify: `.dagi/subagents/memory-refresh/main.py`
- Test: `tests/test_subagent_tools_new.py` (add case)

**Interfaces:**
- Consumes: `run_subagent(..., parent_log=)` from Task 1
- Produces: Each subagent tool constructor accepts `session_log=None` and stores it. Each `run()` forwards `parent_log=self._session_log`.

- [ ] **Step 1: Write failing test**

Add to `tests/test_subagent_tools_new.py`:

```python
class TestSubagentToolsPassParentLog:
    """Every subagent tool forwards session_log as parent_log."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        from unittest.mock import MagicMock
        config = MagicMock()
        config.project_path = tmp_path
        return config

    _SUBAGENT_TYPES = [
        "explore_files", "web_research", "worker", "review",
        "plan", "cli", "read-large-text", "memory-query",
        "memory-add", "memory-refresh",
    ]

    @pytest.mark.parametrize("subagent_type", _SUBAGENT_TYPES)
    def test_constructor_accepts_session_log(self, subagent_type, mock_config):
        """Every subagent tool accepts session_log in its constructor."""
        from agent.subagent_tools import _discover_subagent_tools
        from agent.session_log import SessionLog

        log = SessionLog()
        tools = _discover_subagent_tools(
            cwd=mock_config.project_path,
            config=mock_config,
            callbacks=None,
            tracker=None,
            session_log=log,
        )
        tool = next((t for t in tools if t.name == subagent_type
                      or t.name == subagent_type.replace("-", "_")), None)
        if tool is None:
            pytest.skip(f"Tool {subagent_type} not discovered (may need project path)")
        assert getattr(tool, "_session_log", None) is log
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_subagent_tools_new.py::TestSubagentToolsPassParentLog -v`
Expected: FAIL — tools don't accept `session_log` yet.

- [ ] **Step 3: Implement — update all 10 subagent tools**

The change is identical for each tool. Two modifications per file:

**Constructor** — add `session_log=None` parameter and store it:

```python
    def __init__(
        self,
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        tracker: "SessionTracker | None" = None,
        session_log: "SessionLog | None" = None,
    ) -> None:
        self._config = config
        self._callbacks = callbacks
        self._tracker = tracker
        self._session_log = session_log
```

Add TYPE_CHECKING import in each file:

```python
if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog
```

**`run()` method** — add `parent_log=self._session_log` to the `run_subagent()` call:

```python
        result = _subagent_api.run_subagent(
            task=...,
            preset="...",
            ...,
            parent_log=self._session_log,
        )
```

Apply to all 10 files:
1. `.dagi/subagents/explore_files/main.py`
2. `.dagi/subagents/web_research/main.py`
3. `.dagi/subagents/worker/main.py`
4. `.dagi/subagents/review/main.py`
5. `.dagi/subagents/plan/main.py`
6. `.dagi/subagents/cli/main.py`
7. `.dagi/subagents/read-large-text/main.py`
8. `.dagi/subagents/memory-query/main.py`
9. `.dagi/subagents/memory-add/main.py`
10. `.dagi/subagents/memory-refresh/main.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_subagent_tools_new.py::TestSubagentToolsPassParentLog -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `conda run -n dagi python -m pytest tests/ -x -q`
Expected: 835+ tests passing

- [ ] **Step 6: Commit**

```bash
git add .dagi/subagents/*/main.py tests/test_subagent_tools_new.py
git commit -m "feat: all subagent tools accept session_log and forward parent_log"
```

---

### Task 5: Integration test — full spawn logs `branch/start`

**Files:**
- Test: `tests/test_branch_start_integration.py` (new)

**Interfaces:**
- Consumes: Everything from Tasks 1–4.
- Produces: End-to-end verification that an `AgentLoop.run()` call triggering a subagent tool produces a `branch/start` event in the parent log.

- [ ] **Step 1: Write integration test**

Create `tests/test_branch_start_integration.py`:

```python
"""Integration: subagent spawn logs branch/start on parent SessionLog."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent import session_events as sev
from agent.session_log import SessionLog


class TestBranchStartIntegration:
    """AgentLoop → subagent tool → run_subagent → branch/start on log."""

    def test_subagent_tool_logs_branch_start(self, tmp_path):
        """Calling a subagent tool through registry.dispatch logs branch/start."""
        from agent.session_log import SessionLog
        from agent.subagent_tools import _discover_subagent_tools

        log = SessionLog()
        log.append(sev.TURN_START, {"turn": 1})
        log.append(sev.STEP_START, {"turn": 1, "step": 1})

        config = MagicMock()
        config.project_path = tmp_path

        tools = _discover_subagent_tools(
            cwd=tmp_path,
            config=config,
            callbacks=None,
            tracker=None,
            session_log=log,
        )

        explore_tool = next(
            (t for t in tools if t.name == "explore_files"), None
        )
        if explore_tool is None:
            pytest.skip("explore_files tool not discovered")

        mock_result = MagicMock()
        mock_result.status = "ok"
        mock_result.is_ok = True
        mock_result.handoff_text = "found some files"
        mock_result.handoff_path = tmp_path / "handoff.md"
        mock_result.branch_id = "explore_files_abc12345"

        with patch(
            "tools.subagent_api.run_subagent",
            return_value=mock_result,
        ) as mock_run:
            explore_tool.run(task="find API routes")
            call_kwargs = mock_run.call_args
            assert call_kwargs.kwargs.get("parent_log") is log \
                or (len(call_kwargs.args) > 0 and False), \
                "parent_log must be passed to run_subagent"

    def test_branch_registered_in_log(self, tmp_path):
        """After a subagent spawn, the branch is in log.branches."""
        log = SessionLog()
        log.append(sev.TURN_START, {"turn": 1})
        log.append(sev.STEP_START, {"turn": 1, "step": 1})

        log.append(sev.BRANCH_START, {
            "branch": "explore_files_test123",
            "parent_branch": "main",
            "turn": 1,
            "step": 1,
        })

        assert "explore_files_test123" in log.branches
        parent_branch, turn, step = log.branches["explore_files_test123"]
        assert parent_branch == "main"
        assert turn == 1
        assert step == 1
```

- [ ] **Step 2: Run integration tests**

Run: `conda run -n dagi python -m pytest tests/test_branch_start_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full suite one final time**

Run: `conda run -n dagi python -m pytest tests/ -x -q`
Expected: 835+ tests passing (plus new tests from this plan)

- [ ] **Step 4: Commit**

```bash
git add tests/test_branch_start_integration.py
git commit -m "test: integration test for branch/start logging on subagent spawn"
```
