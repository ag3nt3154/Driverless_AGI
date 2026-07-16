# Esc Force-Kills Active Bash Process Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pressing `Esc` in the TUI force-kills whichever bash process is currently running — the main agent loop's own `bash` tool call, or a bash command inside an active worker/review subagent — instead of only pausing at the next iteration boundary.

**Architecture:** Extract the existing process-tree kill logic from `BashTool._kill_tree` into a shared `agent/_process_kill.py::kill_process_tree()` helper. `BashTool` gains a lock-protected handle to its in-flight `Popen` and a `force_kill()` method. `tools/_subagent_runner.py` gains `force_kill_active_subagents()`, which kills every process tree in the existing `_active` dict. `tui/app.py`'s `action_pause()` (bound to `escape`) calls both, then proceeds with its existing `loop.pause()` behavior unchanged.

**Tech Stack:** Python 3.14, `subprocess`, `threading`, pytest. No new dependencies.

Spec: `docs/superpowers/specs/2026-07-16-esc-force-kill-bash-design.md`

---

### Task 1: Shared `kill_process_tree()` helper

**Files:**
- Create: `agent/_process_kill.py`
- Test: `tests/test_process_kill.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_process_kill.py`:

```python
"""tests/test_process_kill.py — Unit test for agent/_process_kill.py."""
from __future__ import annotations

import subprocess
import sys
import time

from agent._process_kill import kill_process_tree


def test_kill_process_tree_terminates_a_running_process():
    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        **popen_kwargs,
    )
    time.sleep(0.5)  # let it actually start

    kill_process_tree(proc)

    proc.wait(timeout=5)
    assert proc.returncode is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_process_kill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent._process_kill'`

- [ ] **Step 3: Write the implementation**

Create `agent/_process_kill.py`:

```python
"""agent/_process_kill.py — Shared process-tree kill helper.

Used by tools/bash.py (timeout kills and user-triggered force_kill()) and
tools/_subagent_runner.py (Esc-triggered subagent kill) so there is one
place that knows how to forcibly kill a full process tree on both platforms.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill the whole process tree, not just the shell's direct child."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_process_kill.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/_process_kill.py tests/test_process_kill.py
git commit -m "feat: add shared kill_process_tree() helper"
```

---

### Task 2: Refactor `BashTool` to use the shared helper (no behavior change)

**Files:**
- Modify: `tools/bash.py`

- [ ] **Step 1: Replace the whole file**

`tools/bash.py` currently defines `_kill_tree` as a static method with the exact logic just extracted in Task 1. Replace the file so it imports and calls the shared helper instead of duplicating it. This step is a pure refactor — no behavior change yet (that's Task 3).

Write `tools/bash.py`:

```python
import subprocess
import sys
from pathlib import Path

from agent.base_tool import BaseTool
from agent._process_kill import kill_process_tree


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Execute a bash command within the project directory. "
        "Returns stdout and stderr. Optionally provide a timeout in seconds "
        "(defaults to 120s if omitted)."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (optional)"},
        },
        "required": ["command"],
    }

    DEFAULT_TIMEOUT = 120.0
    _REAP_GRACE = 5.0  # seconds to wait for a killed tree to release its output pipes

    def __init__(self, cwd: Path = Path("."), default_timeout: float = DEFAULT_TIMEOUT):
        self.cwd = cwd
        self.default_timeout = default_timeout

    def run(self, command: str, timeout: int | None = None) -> str:
        effective_timeout = timeout if timeout is not None else self.default_timeout

        popen_kwargs: dict = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.cwd),
            **popen_kwargs,
        )
        try:
            stdout, stderr = proc.communicate(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc)
            # A shelled-out command tree (e.g. npm -> node) can leave grandchild
            # processes holding the stdout/stderr pipes open even after the
            # immediate shell is killed, so this drain is itself bounded.
            try:
                proc.communicate(timeout=self._REAP_GRACE)
            except subprocess.TimeoutExpired:
                pass
            return (
                f"[timed out after {effective_timeout}s and was terminated — "
                "pass a longer explicit timeout for long-running commands]"
            )

        output = (stdout or "") + (stderr or "")
        if proc.returncode != 0:
            output += f"\n[exit code {proc.returncode}]"
        return output or "[no output]"
```

- [ ] **Step 2: Run the existing bash tool tests to confirm nothing broke**

Run: `conda run -n dagi python -m pytest tests/test_bash_tools.py -v`
Expected: PASS (all existing tests, including `test_hanging_command_is_bounded_by_default_timeout`)

- [ ] **Step 3: Commit**

```bash
git add tools/bash.py
git commit -m "refactor: BashTool uses shared kill_process_tree() helper"
```

---

### Task 3: `BashTool.force_kill()` — Esc kills the running command

**Files:**
- Modify: `tools/bash.py`
- Test: `tests/test_bash_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_bash_tools.py`. First add `import threading` to the top-of-file imports (alongside the existing `import sys`, `import time`):

```python
import sys
import threading
import time
```

Then add a new test class at the end of the file:

```python
class TestForceKill:
    def test_force_kill_terminates_running_command_immediately(self):
        """Esc-triggered force_kill() must interrupt a running command without
        waiting for its timeout."""
        tool = BashTool(cwd=Path("."), default_timeout=30.0)
        command = f'"{sys.executable}" -c "import time; time.sleep(10)"'
        result_holder: dict = {}

        def _run():
            result_holder["result"] = tool.run(command=command)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(0.5)  # let the subprocess actually start

        killed = tool.force_kill()
        t.join(timeout=5)

        assert killed is True
        assert not t.is_alive(), "run() did not return promptly after force_kill()"
        assert "[killed by user]" in result_holder["result"]

    def test_force_kill_returns_false_when_nothing_running(self):
        tool = BashTool(cwd=Path("."))
        assert tool.force_kill() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_bash_tools.py::TestForceKill -v`
Expected: FAIL with `AttributeError: 'BashTool' object has no attribute 'force_kill'`

- [ ] **Step 3: Implement `force_kill()` in `BashTool`**

In `tools/bash.py`, add `import threading` to the imports:

```python
import subprocess
import sys
import threading
from pathlib import Path

from agent.base_tool import BaseTool
from agent._process_kill import kill_process_tree
```

Replace `__init__`:

```python
    def __init__(self, cwd: Path = Path("."), default_timeout: float = DEFAULT_TIMEOUT):
        self.cwd = cwd
        self.default_timeout = default_timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._killed_by_user = False
```

Replace `run()`:

```python
    def run(self, command: str, timeout: int | None = None) -> str:
        effective_timeout = timeout if timeout is not None else self.default_timeout

        popen_kwargs: dict = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.cwd),
            **popen_kwargs,
        )
        with self._lock:
            self._proc = proc
            self._killed_by_user = False
        try:
            try:
                stdout, stderr = proc.communicate(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                kill_process_tree(proc)
                # A shelled-out command tree (e.g. npm -> node) can leave grandchild
                # processes holding the stdout/stderr pipes open even after the
                # immediate shell is killed, so this drain is itself bounded.
                try:
                    proc.communicate(timeout=self._REAP_GRACE)
                except subprocess.TimeoutExpired:
                    pass
                return (
                    f"[timed out after {effective_timeout}s and was terminated — "
                    "pass a longer explicit timeout for long-running commands]"
                )
        finally:
            with self._lock:
                self._proc = None

        output = (stdout or "") + (stderr or "")
        if self._killed_by_user:
            return f"{output}\n[killed by user]" if output else "[killed by user]"
        if proc.returncode != 0:
            output += f"\n[exit code {proc.returncode}]"
        return output or "[no output]"

    def force_kill(self) -> bool:
        """Force-kill the currently running command, if any. Returns whether
        anything was actually killed."""
        with self._lock:
            proc = self._proc
            if proc is None:
                return False
            self._killed_by_user = True
        kill_process_tree(proc)
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_bash_tools.py -v`
Expected: PASS (all tests, including the two new `TestForceKill` tests and the pre-existing timeout test)

- [ ] **Step 5: Commit**

```bash
git add tools/bash.py tests/test_bash_tools.py
git commit -m "feat: BashTool.force_kill() interrupts a running command on demand"
```

---

### Task 4: `force_kill_active_subagents()` — Esc kills the running subagent

**Files:**
- Modify: `tools/_subagent_runner.py`
- Test: `tests/test_subagent_runner.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_subagent_runner.py`. First add the shared-helper import alongside the existing imports at the top of the file:

```python
from tools._subagent_runner import _poll_until, _SubagentState
```

becomes:

```python
from tools import _subagent_runner
from tools._subagent_runner import _poll_until, _SubagentState
```

Then add a new test class at the end of the file:

```python
class TestForceKillActiveSubagents:
    def test_force_kill_calls_kill_process_tree_on_every_active_proc(self, tmp_path, monkeypatch):
        killed_procs = []
        monkeypatch.setattr(
            "tools._subagent_runner.kill_process_tree",
            lambda proc: killed_procs.append(proc),
        )
        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)
        with _subagent_runner._active_lock:
            _subagent_runner._active[proc.pid] = state

        try:
            killed_count = _subagent_runner.force_kill_active_subagents()
        finally:
            with _subagent_runner._active_lock:
                _subagent_runner._active.pop(proc.pid, None)

        assert killed_count == 1
        assert killed_procs == [proc]

    def test_force_kill_returns_zero_when_no_active_subagents(self):
        assert _subagent_runner.force_kill_active_subagents() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_subagent_runner.py::TestForceKillActiveSubagents -v`
Expected: FAIL with `AttributeError: module 'tools._subagent_runner' has no attribute 'force_kill_active_subagents'`

- [ ] **Step 3: Implement `force_kill_active_subagents()`**

In `tools/_subagent_runner.py`, add the import alongside the existing ones near the top:

```python
from agent import DAGI_ROOT as _DAGI_ROOT
from agent._process_kill import kill_process_tree
```

Add the new function after `_poll_until` and before `run_subagent`:

```python
def force_kill_active_subagents() -> int:
    """Force-kill every currently in-flight subagent's process tree.

    Best-effort and does not mutate _active directly — _poll_until()'s own
    exit-detection path removes each entry once it observes the process is
    gone. Returns the number of processes killed.
    """
    with _active_lock:
        states = list(_active.values())
    killed = 0
    for state in states:
        kill_process_tree(state.proc)
        killed += 1
    return killed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_subagent_runner.py -v`
Expected: PASS (all tests, including the two new `TestForceKillActiveSubagents` tests)

- [ ] **Step 5: Commit**

```bash
git add tools/_subagent_runner.py tests/test_subagent_runner.py
git commit -m "feat: force_kill_active_subagents() kills in-flight subagent process trees"
```

---

### Task 5: Wire into `tui/app.py`'s `action_pause()`

**Files:**
- Modify: `tui/app.py:124-140`

- [ ] **Step 1: Replace `action_pause()`**

Current code at `tui/app.py:124-140`:

```python
    def action_pause(self) -> None:
        if not (self._worker and self._worker.is_alive()):
            return
        if self._pending_ask is not None:
            return
        if not self._current_loop_ref:
            return
        loop = self._current_loop_ref[0]
        if not loop._pause_event.is_set():
            return  # already paused
        loop.pause()
        self.query_one(Sidebar).set_status("paused")
        self.query_one(ConversationPane).append_info(
            "[yellow]⏸ Paused — type a message and press Enter to continue[/yellow]"
        )
        self._hide_running_indicator()
        self._enable_input()
```

Replace with:

```python
    def action_pause(self) -> None:
        if not (self._worker and self._worker.is_alive()):
            return
        if self._pending_ask is not None:
            return
        if not self._current_loop_ref:
            return
        loop = self._current_loop_ref[0]
        if not loop._pause_event.is_set():
            return  # already paused
        bash_tool = loop.registry._tools.get("bash")
        if bash_tool is not None:
            bash_tool.force_kill()
        from tools._subagent_runner import force_kill_active_subagents
        force_kill_active_subagents()
        loop.pause()
        self.query_one(Sidebar).set_status("paused")
        self.query_one(ConversationPane).append_info(
            "[yellow]⏸ Paused — type a message and press Enter to continue[/yellow]"
        )
        self._hide_running_indicator()
        self._enable_input()
```

- [ ] **Step 2: Run the full test suite to confirm nothing broke**

Run: `conda run -n dagi python -m pytest tests/ -q`
Expected: PASS (same pass count as before this plan, plus the 6 new tests added in Tasks 1, 3, and 4 — pre-existing `dagi_eval` failures from missing `numpy` are unrelated, per `TODO.md`)

- [ ] **Step 3: Manually verify in the running TUI**

There is no automated Textual test for this wiring (it's a 5-line addition with no new UI state). Verify by hand per the `verify` skill:

1. `conda run --no-capture-output -n dagi python tui.py`
2. Give it a task that runs a long bash command, e.g. `Run this bash command: python -c "import time; time.sleep(30)"`
3. While it's running, press `Esc`.
4. Confirm: the command is killed almost immediately (not after 30s), the conversation pane shows `[killed by user]` in the tool result, and the status switches to `⏸ Paused`.
5. Type a message and press Enter — confirm the agent resumes normally.
6. Repeat with a task that spawns a worker or review subagent running a long bash command inside it (e.g. via `/plan` → approve → a subtask that runs a slow test command), press `Esc` mid-subagent, and confirm the subagent's process is killed and the main loop pauses with an error tool result for the `spawn_*_subagent` call.

- [ ] **Step 4: Commit**

```bash
git add tui/app.py
git commit -m "feat: Esc force-kills the active bash process (main loop and subagents)"
```

---

### Task 6: Update `README.md` and `TODO.md`

**Files:**
- Modify: `README.md`
- Modify: `TODO.md`

- [ ] **Step 1: Update the Esc keybinding description in `README.md`**

`README.md:119` currently reads:

```
- `Esc` — pause the running agent at the end of the current iteration (after all tool calls in the current LLM response complete). Status changes to `⏸ Paused`. Type any message and press Enter to inject it into the agent's context and resume. ESC has no effect when idle or during an `ask_user` prompt.
```

Replace with:

```
- `Esc` — pause the running agent. If a `bash` command is currently running (in the main loop or inside an active worker/review subagent), it is force-killed immediately; otherwise the agent pauses at the end of the current iteration (after all tool calls in the current LLM response complete). Status changes to `⏸ Paused`. Type any message and press Enter to inject it into the agent's context and resume. ESC has no effect when idle or during an `ask_user` prompt.
```

Also update the "Pausing and Resuming" section (`README.md:316-322`). Current text:

```
Press `Esc` at any time while the agent is running to pause it at the end of the current iteration (after all tool calls in the current LLM response complete). The status indicator switches to `⏸ Paused`.
```

Replace with:

```
Press `Esc` at any time while the agent is running to pause it. If a `bash` command is currently running — in the main loop, or inside an active worker/review subagent — it is force-killed immediately (surfaced as `[killed by user]` in the conversation, or as a tool error for the subagent call). Otherwise, the agent pauses at the end of the current iteration (after all tool calls in the current LLM response complete). The status indicator switches to `⏸ Paused`.
```

- [ ] **Step 2: Add a completed entry to `TODO.md`**

Add to the top of the `## Completed` section in `TODO.md` (after the `# TODO` / `## Completed` header, before the existing top entry):

```markdown
- **`Esc` now force-kills the active bash process (main loop and subagents)** · `done` · `2026-07-16`
  - **Problem:** `Esc` only set `AgentLoop._pause_event`, checked between iterations — a hung or long-running `bash` command (main loop or inside a worker/review subagent) couldn't be interrupted; you had to wait out its timeout.
  - **Fix:** Extracted `BashTool._kill_tree` into a shared `agent/_process_kill.py::kill_process_tree()`. `BashTool` gained a lock-protected `force_kill()` that kills its in-flight `Popen` and makes `run()` return `[killed by user]`. `tools/_subagent_runner.py` gained `force_kill_active_subagents()`, which kills every process tree in the existing `_active` dict. `tui/app.py::action_pause()` calls both before `loop.pause()`.
  - **Scope:** at most one of "main-loop bash" or "an active subagent" is ever running at once (the main loop blocks synchronously on subagent polling), so `Esc` doesn't need to disambiguate — it attempts both kills unconditionally and whichever has nothing active is a no-op.
  - Spec: `docs/superpowers/specs/2026-07-16-esc-force-kill-bash-design.md`. Plan: `docs/superpowers/plans/2026-07-16-esc-force-kill-bash.md`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md TODO.md
git commit -m "docs: update README and TODO for Esc force-kill feature"
```
