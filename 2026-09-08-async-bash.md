# Async Bash Tools + Processes Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the agent start long-running bash commands asynchronously, poll their stdout, and kill them — with a live "Processes" tab in the PySide6 left sidebar showing real-time output from every background process.

**Architecture:** A `BgProcessManager` owns a dict of background process handles, each with a reader thread streaming stdout/stderr into a `deque` ring buffer. Three new tools (`bash_start`, `bash_status`, `bash_kill`) delegate to the manager and return immediately. The manager fires callbacks (`on_bg_started`, `on_bg_output`, `on_bg_finished`) which the PySide6 bridge translates into Qt signals consumed by a new `ProcessesView` sidebar tab. The synchronous `bash` tool is untouched.

**Tech Stack:** Python 3.14, `subprocess`, `threading`, `collections.deque`, PySide6, pytest. No new dependencies.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `tools/bash/_bg_manager.py` | `BgProcessManager` — owns background process lifecycle, reader threads, ring buffers, callbacks |
| Create | `tools/bash/_bash_start.py` | `BashStartTool` — starts a background command via the manager |
| Create | `tools/bash/_bash_status.py` | `BashStatusTool` — reads tail of a process's output buffer |
| Create | `tools/bash/_bash_kill.py` | `BashKillTool` — kills a background process and returns final output |
| Modify | `tools/bash/__init__.py` | Re-export the three new tool classes |
| Modify | `agent/_loop_config.py:110-163` | Add `on_bg_started`, `on_bg_output`, `on_bg_finished` callbacks |
| Modify | `agent/tools.py:158` | Instantiate `BgProcessManager`, register the three new tools |
| Create | `pyside_gui/sidebars/processes_view.py` | `ProcessesView` QWidget — live output display per background process |
| Modify | `pyside_gui/sidebars/__init__.py` | Export `ProcessesView` |
| Modify | `pyside_gui/left_sidebar.py:22-23` | Add `"processes"` to `_VIEW_NAMES` and icon to `_RAIL_ICONS` |
| Modify | `pyside_gui/left_sidebar.py:98-107` | Instantiate and add `ProcessesView` to the stacked widget |
| Modify | `pyside_gui/bridge.py` | Add `bg_started`, `bg_output`, `bg_finished` signals + wire in `build_callbacks` |
| Modify | `pyside_gui/app.py` | Connect bridge signals to the processes view |
| Create | `tests/test_bg_manager.py` | Unit tests for `BgProcessManager` |
| Create | `tests/test_bash_start.py` | Unit tests for `BashStartTool` |
| Create | `tests/test_bash_status.py` | Unit tests for `BashStatusTool` |
| Create | `tests/test_bash_kill.py` | Unit tests for `BashKillTool` |

---

### Task 1: `BgProcessManager` — core process lifecycle

**Files:**
- Create: `tools/bash/_bg_manager.py`
- Test: `tests/test_bg_manager.py`

- [ ] **Step 1: Write the failing test — start and read output**

Create `tests/test_bg_manager.py`:

```python
"""tests/test_bg_manager.py — Unit tests for BgProcessManager."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from tools.bash._bg_manager import BgProcessManager


class TestBgProcessManagerStart:
    def test_start_returns_handle_id(self):
        mgr = BgProcessManager(cwd=Path("."))
        handle = mgr.start(f'"{sys.executable}" -c "print(42)"')
        assert isinstance(handle, str)
        assert len(handle) >= 4
        mgr.kill(handle)

    def test_output_captured_in_buffer(self):
        mgr = BgProcessManager(cwd=Path("."))
        handle = mgr.start(f'"{sys.executable}" -c "print(42)"')
        time.sleep(1.0)
        lines = mgr.read_output(handle, tail=10)
        assert any("42" in line for line in lines)
        mgr.kill(handle)

    def test_process_completes_and_reports_exit_code(self):
        mgr = BgProcessManager(cwd=Path("."))
        handle = mgr.start(f'"{sys.executable}" -c "print(1)"')
        time.sleep(1.0)
        info = mgr.status(handle)
        assert info["running"] is False
        assert info["exit_code"] == 0
        mgr.kill(handle)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_bg_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.bash._bg_manager'`

- [ ] **Step 3: Write the implementation**

Create `tools/bash/_bg_manager.py`:

```python
"""tools/bash/_bg_manager.py — Background process manager.

Owns the lifecycle of asynchronously-started bash processes. Each process
gets a reader thread that streams stdout+stderr into a bounded deque.
"""
from __future__ import annotations

import subprocess
import sys
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent._process_kill import kill_process_tree

_REAP_GRACE = 5.0
_BUFFER_MAXLEN = 2000
_REAP_AGE = 600.0  # seconds after death before auto-reap


@dataclass
class BgProcess:
    handle: str
    command: str
    proc: subprocess.Popen
    buffer: deque = field(default_factory=lambda: deque(maxlen=_BUFFER_MAXLEN))
    lock: threading.Lock = field(default_factory=threading.Lock)
    completed: bool = False
    exit_code: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    _reader: threading.Thread | None = None


class BgProcessManager:
    def __init__(
        self,
        cwd: Path = Path("."),
        on_started: Callable[[str, str], None] | None = None,
        on_output: Callable[[str, str], None] | None = None,
        on_finished: Callable[[str, int], None] | None = None,
    ) -> None:
        self.cwd = cwd
        self._on_started = on_started
        self._on_output = on_output
        self._on_finished = on_finished
        self._processes: dict[str, BgProcess] = {}
        self._lock = threading.Lock()

    def start(self, command: str, timeout: float = 600.0) -> str:
        handle = secrets.token_hex(4)

        popen_kwargs: dict = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(self.cwd),
            **popen_kwargs,
        )

        bg = BgProcess(handle=handle, command=command, proc=proc)
        reader = threading.Thread(
            target=self._reader_loop, args=(bg,), daemon=True,
        )
        bg._reader = reader

        with self._lock:
            self._processes[handle] = bg

        reader.start()

        # Auto-kill after timeout
        timer = threading.Thread(
            target=self._timeout_watchdog, args=(bg, timeout), daemon=True,
        )
        timer.start()

        if self._on_started:
            self._on_started(handle, command)

        self._reap_stale()
        return handle

    def read_output(self, handle: str, tail: int = 50) -> list[str]:
        bg = self._get(handle)
        if bg is None:
            return []
        with bg.lock:
            items = list(bg.buffer)
        return items[-tail:]

    def status(self, handle: str) -> dict:
        bg = self._get(handle)
        if bg is None:
            return {"error": f"Unknown handle: {handle}"}
        with bg.lock:
            return {
                "handle": handle,
                "command": bg.command,
                "running": not bg.completed,
                "exit_code": bg.exit_code,
                "lines_buffered": len(bg.buffer),
            }

    def kill(self, handle: str) -> dict:
        bg = self._get(handle)
        if bg is None:
            return {"error": f"Unknown handle: {handle}"}
        if not bg.completed:
            kill_process_tree(bg.proc)
            try:
                bg.proc.communicate(timeout=_REAP_GRACE)
            except subprocess.TimeoutExpired:
                pass
            with bg.lock:
                bg.completed = True
                bg.exit_code = bg.proc.returncode
                bg.finished_at = time.monotonic()
        output = self.read_output(handle, tail=100)
        return {
            "exit_code": bg.exit_code,
            "output_tail": output,
        }

    def list_handles(self) -> list[dict]:
        with self._lock:
            return [self.status(h) for h in self._processes]

    def _get(self, handle: str) -> BgProcess | None:
        with self._lock:
            return self._processes.get(handle)

    def _reader_loop(self, bg: BgProcess) -> None:
        assert bg.proc.stdout is not None
        try:
            for line in bg.proc.stdout:
                stripped = line.rstrip("\n")
                with bg.lock:
                    bg.buffer.append(stripped)
                if self._on_output:
                    self._on_output(bg.handle, stripped)
        except ValueError:
            pass  # stdout closed
        bg.proc.wait()
        with bg.lock:
            bg.completed = True
            bg.exit_code = bg.proc.returncode
            bg.finished_at = time.monotonic()
        if self._on_finished:
            self._on_finished(bg.handle, bg.proc.returncode or 0)

    def _timeout_watchdog(self, bg: BgProcess, timeout: float) -> None:
        deadline = bg.started_at + timeout
        while time.monotonic() < deadline:
            if bg.completed:
                return
            time.sleep(1.0)
        if not bg.completed:
            kill_process_tree(bg.proc)

    def _reap_stale(self) -> None:
        now = time.monotonic()
        with self._lock:
            to_remove = [
                h for h, bg in self._processes.items()
                if bg.completed
                and bg.finished_at is not None
                and (now - bg.finished_at) > _REAP_AGE
            ]
            for h in to_remove:
                del self._processes[h]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_bg_manager.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/bash/_bg_manager.py tests/test_bg_manager.py
git commit -m "feat: add BgProcessManager for async bash process lifecycle"
```

---

### Task 2: Write additional `BgProcessManager` tests

**Files:**
- Modify: `tests/test_bg_manager.py`

- [ ] **Step 1: Add tests for kill, callbacks, unknown handle, and reap**

Append to `tests/test_bg_manager.py`:

```python
class TestBgProcessManagerKill:
    def test_kill_terminates_running_process(self):
        mgr = BgProcessManager(cwd=Path("."))
        handle = mgr.start(f'"{sys.executable}" -c "import time; time.sleep(30)"')
        time.sleep(0.5)
        result = mgr.kill(handle)
        assert result["exit_code"] is not None
        info = mgr.status(handle)
        assert info["running"] is False

    def test_kill_unknown_handle_returns_error(self):
        mgr = BgProcessManager(cwd=Path("."))
        result = mgr.kill("nonexistent")
        assert "error" in result


class TestBgProcessManagerCallbacks:
    def test_on_started_fires(self):
        events: list = []
        mgr = BgProcessManager(
            cwd=Path("."),
            on_started=lambda h, c: events.append(("started", h, c)),
        )
        handle = mgr.start(f'"{sys.executable}" -c "print(1)"')
        assert len(events) == 1
        assert events[0][0] == "started"
        assert events[0][1] == handle
        mgr.kill(handle)

    def test_on_output_fires_per_line(self):
        lines: list = []
        mgr = BgProcessManager(
            cwd=Path("."),
            on_output=lambda h, line: lines.append(line),
        )
        handle = mgr.start(f'"{sys.executable}" -c "print(\'aaa\'); print(\'bbb\')"')
        time.sleep(1.0)
        assert "aaa" in lines
        assert "bbb" in lines
        mgr.kill(handle)

    def test_on_finished_fires(self):
        events: list = []
        mgr = BgProcessManager(
            cwd=Path("."),
            on_finished=lambda h, code: events.append(("done", h, code)),
        )
        handle = mgr.start(f'"{sys.executable}" -c "print(1)"')
        time.sleep(1.0)
        assert any(e[0] == "done" for e in events)
        mgr.kill(handle)


class TestBgProcessManagerListHandles:
    def test_list_handles_returns_all(self):
        mgr = BgProcessManager(cwd=Path("."))
        h1 = mgr.start(f'"{sys.executable}" -c "import time; time.sleep(5)"')
        h2 = mgr.start(f'"{sys.executable}" -c "import time; time.sleep(5)"')
        handles = mgr.list_handles()
        handle_ids = [h["handle"] for h in handles]
        assert h1 in handle_ids
        assert h2 in handle_ids
        mgr.kill(h1)
        mgr.kill(h2)
```

- [ ] **Step 2: Run all tests**

Run: `conda run -n dagi python -m pytest tests/test_bg_manager.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_bg_manager.py
git commit -m "test: add kill, callback, and list_handles tests for BgProcessManager"
```

---

### Task 3: `BashStartTool`

**Files:**
- Create: `tools/bash/_bash_start.py`
- Test: `tests/test_bash_start.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bash_start.py`:

```python
"""tests/test_bash_start.py — Unit tests for BashStartTool."""
from __future__ import annotations

import sys
from pathlib import Path

from tools.bash._bg_manager import BgProcessManager
from tools.bash._bash_start import BashStartTool


class TestBashStartTool:
    def _make_tool(self) -> tuple[BashStartTool, BgProcessManager]:
        mgr = BgProcessManager(cwd=Path("."))
        tool = BashStartTool(manager=mgr)
        return tool, mgr

    def test_returns_handle_in_output(self):
        tool, mgr = self._make_tool()
        result = tool.run(command=f'"{sys.executable}" -c "print(1)"')
        assert "handle" in result.lower() or len(result) >= 4
        # Clean up
        for h in [s["handle"] for s in mgr.list_handles()]:
            mgr.kill(h)

    def test_schema_has_required_fields(self):
        tool, _ = self._make_tool()
        schema = tool.schema()
        assert schema["function"]["name"] == "bash_start"
        params = schema["function"]["parameters"]
        assert "command" in params["properties"]
        assert "command" in params["required"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_bash_start.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.bash._bash_start'`

- [ ] **Step 3: Write the implementation**

Create `tools/bash/_bash_start.py`:

```python
"""tools/bash/_bash_start.py — Start a background bash process."""
from __future__ import annotations

from typing import TYPE_CHECKING

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from tools.bash._bg_manager import BgProcessManager


class BashStartTool(BaseTool):
    name = "bash_start"
    description = (
        "Start a long-running bash command in the background. Returns a handle ID "
        "immediately. Use bash_status to check output and bash_kill to terminate. "
        "Use this instead of bash for commands that take more than ~30 seconds "
        "(servers, watchers, long builds, test suites)."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Bash command to execute in the background",
            },
            "timeout": {
                "type": "integer",
                "description": (
                    "Maximum lifetime in seconds before auto-kill (default 600)"
                ),
            },
        },
        "required": ["command"],
    }

    def __init__(self, manager: BgProcessManager) -> None:
        self._manager = manager

    def run(self, command: str, timeout: int | None = None) -> str:
        effective_timeout = timeout if timeout is not None else 600
        handle = self._manager.start(command, timeout=float(effective_timeout))
        return (
            f"Started background process [{handle}].\n"
            f"Command: {command}\n"
            f"Timeout: {effective_timeout}s\n"
            f"Use bash_status(handle_id=\"{handle}\") to check output.\n"
            f"Use bash_kill(handle_id=\"{handle}\") to terminate."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_bash_start.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/bash/_bash_start.py tests/test_bash_start.py
git commit -m "feat: add BashStartTool for launching background bash processes"
```

---

### Task 4: `BashStatusTool`

**Files:**
- Create: `tools/bash/_bash_status.py`
- Test: `tests/test_bash_status.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bash_status.py`:

```python
"""tests/test_bash_status.py — Unit tests for BashStatusTool."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from tools.bash._bg_manager import BgProcessManager
from tools.bash._bash_status import BashStatusTool


class TestBashStatusTool:
    def _make_tool(self) -> tuple[BashStatusTool, BgProcessManager]:
        mgr = BgProcessManager(cwd=Path("."))
        tool = BashStatusTool(manager=mgr)
        return tool, mgr

    def test_shows_output_and_running_state(self):
        tool, mgr = self._make_tool()
        handle = mgr.start(
            f'"{sys.executable}" -c "import time; print(\'hello\'); time.sleep(5)"'
        )
        time.sleep(1.0)
        result = tool.run(handle_id=handle)
        assert "hello" in result
        assert "running" in result.lower()
        mgr.kill(handle)

    def test_shows_exit_code_when_done(self):
        tool, mgr = self._make_tool()
        handle = mgr.start(f'"{sys.executable}" -c "print(\'done\')"')
        time.sleep(1.0)
        result = tool.run(handle_id=handle)
        assert "exit code" in result.lower() or "exit_code" in result.lower()
        mgr.kill(handle)

    def test_unknown_handle_returns_error(self):
        tool, _ = self._make_tool()
        result = tool.run(handle_id="nonexistent")
        assert "error" in result.lower() or "unknown" in result.lower()

    def test_schema_has_required_fields(self):
        tool, _ = self._make_tool()
        schema = tool.schema()
        assert schema["function"]["name"] == "bash_status"
        assert "handle_id" in schema["function"]["parameters"]["properties"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_bash_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.bash._bash_status'`

- [ ] **Step 3: Write the implementation**

Create `tools/bash/_bash_status.py`:

```python
"""tools/bash/_bash_status.py — Check output of a background bash process."""
from __future__ import annotations

from typing import TYPE_CHECKING

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from tools.bash._bg_manager import BgProcessManager


class BashStatusTool(BaseTool):
    name = "bash_status"
    description = (
        "Check the output and status of a background bash process started with "
        "bash_start. Returns the most recent lines of stdout/stderr and whether "
        "the process is still running."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "handle_id": {
                "type": "string",
                "description": "Handle ID returned by bash_start",
            },
            "lines": {
                "type": "integer",
                "description": "Number of recent lines to return (default 50)",
            },
        },
        "required": ["handle_id"],
    }

    def __init__(self, manager: BgProcessManager) -> None:
        self._manager = manager

    def run(self, handle_id: str, lines: int | None = None) -> str:
        tail = lines if lines is not None else 50
        info = self._manager.status(handle_id)
        if "error" in info:
            return f"Error: {info['error']}"

        output_lines = self._manager.read_output(handle_id, tail=tail)
        output_text = "\n".join(output_lines) if output_lines else "[no output yet]"

        status = "RUNNING" if info["running"] else "FINISHED"
        header = f"[{handle_id}] Status: {status}"
        if not info["running"]:
            header += f" | Exit code: {info['exit_code']}"
        header += f" | Lines buffered: {info['lines_buffered']}"

        return f"{header}\n--- recent output ({len(output_lines)} lines) ---\n{output_text}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_bash_status.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/bash/_bash_status.py tests/test_bash_status.py
git commit -m "feat: add BashStatusTool for polling background process output"
```

---

### Task 5: `BashKillTool`

**Files:**
- Create: `tools/bash/_bash_kill.py`
- Test: `tests/test_bash_kill.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bash_kill.py`:

```python
"""tests/test_bash_kill.py — Unit tests for BashKillTool."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from tools.bash._bg_manager import BgProcessManager
from tools.bash._bash_kill import BashKillTool


class TestBashKillTool:
    def _make_tool(self) -> tuple[BashKillTool, BgProcessManager]:
        mgr = BgProcessManager(cwd=Path("."))
        tool = BashKillTool(manager=mgr)
        return tool, mgr

    def test_kills_running_process_and_returns_output(self):
        tool, mgr = self._make_tool()
        handle = mgr.start(
            f'"{sys.executable}" -c "import time; print(\'hi\'); time.sleep(30)"'
        )
        time.sleep(1.0)
        result = tool.run(handle_id=handle)
        assert "killed" in result.lower() or "exit" in result.lower()
        info = mgr.status(handle)
        assert info["running"] is False

    def test_kill_already_finished_process(self):
        tool, mgr = self._make_tool()
        handle = mgr.start(f'"{sys.executable}" -c "print(\'done\')"')
        time.sleep(1.0)
        result = tool.run(handle_id=handle)
        assert "exit" in result.lower()

    def test_kill_unknown_handle_returns_error(self):
        tool, _ = self._make_tool()
        result = tool.run(handle_id="nonexistent")
        assert "error" in result.lower() or "unknown" in result.lower()

    def test_schema_has_required_fields(self):
        tool, _ = self._make_tool()
        schema = tool.schema()
        assert schema["function"]["name"] == "bash_kill"
        assert "handle_id" in schema["function"]["parameters"]["properties"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_bash_kill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.bash._bash_kill'`

- [ ] **Step 3: Write the implementation**

Create `tools/bash/_bash_kill.py`:

```python
"""tools/bash/_bash_kill.py — Kill a background bash process."""
from __future__ import annotations

from typing import TYPE_CHECKING

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from tools.bash._bg_manager import BgProcessManager


class BashKillTool(BaseTool):
    name = "bash_kill"
    description = (
        "Kill a background bash process started with bash_start. Returns the "
        "final output tail and exit code."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "handle_id": {
                "type": "string",
                "description": "Handle ID returned by bash_start",
            },
        },
        "required": ["handle_id"],
    }

    def __init__(self, manager: BgProcessManager) -> None:
        self._manager = manager

    def run(self, handle_id: str) -> str:
        result = self._manager.kill(handle_id)
        if "error" in result:
            return f"Error: {result['error']}"

        output_lines = result.get("output_tail", [])
        output_text = "\n".join(output_lines) if output_lines else "[no output]"
        exit_code = result.get("exit_code")

        return (
            f"Process [{handle_id}] killed.\n"
            f"Exit code: {exit_code}\n"
            f"--- final output ({len(output_lines)} lines) ---\n{output_text}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_bash_kill.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/bash/_bash_kill.py tests/test_bash_kill.py
git commit -m "feat: add BashKillTool for terminating background bash processes"
```

---

### Task 6: Update `tools/bash/__init__.py` and register tools

**Files:**
- Modify: `tools/bash/__init__.py`
- Modify: `agent/tools.py:158`

- [ ] **Step 1: Update the bash package exports**

Edit `tools/bash/__init__.py` to become:

```python
from tools.bash._bash import BashTool
from tools.bash._bg_manager import BgProcessManager
from tools.bash._bash_start import BashStartTool
from tools.bash._bash_status import BashStatusTool
from tools.bash._bash_kill import BashKillTool

__all__ = ["BashTool", "BgProcessManager", "BashStartTool", "BashStatusTool", "BashKillTool"]
```

- [ ] **Step 2: Register the tools in `agent/tools.py`**

In `agent/tools.py`, after the line `reg.register(BashTool(cwd=cwd))` (line 158), add:

```python
    from tools.bash import BgProcessManager, BashStartTool, BashStatusTool, BashKillTool
    _bg_manager = BgProcessManager(
        cwd=cwd,
        on_started=callbacks.on_bg_started if callbacks else None,
        on_output=callbacks.on_bg_output if callbacks else None,
        on_finished=callbacks.on_bg_finished if callbacks else None,
    )
    reg.register(BashStartTool(manager=_bg_manager))
    reg.register(BashStatusTool(manager=_bg_manager))
    reg.register(BashKillTool(manager=_bg_manager))
```

- [ ] **Step 3: Run existing bash tests to verify no regressions**

Run: `conda run -n dagi python -m pytest tests/test_bash_tools.py tests/test_bash_start.py tests/test_bash_status.py tests/test_bash_kill.py tests/test_bg_manager.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tools/bash/__init__.py agent/tools.py
git commit -m "feat: register async bash tools (bash_start, bash_status, bash_kill) in tool registry"
```

---

### Task 7: Add callback fields to `AgentCallbacks`

**Files:**
- Modify: `agent/_loop_config.py:160-163`

- [ ] **Step 1: Add the three new callback fields**

In `agent/_loop_config.py`, after the `on_message_board_post` field (around line 161), add:

```python
    # Background process events (bash_start / bash_status / bash_kill tools)
    on_bg_started:  Callable[[str, str], None] = field(default=lambda handle, cmd: None)
    on_bg_output:   Callable[[str, str], None] = field(default=lambda handle, line: None)
    on_bg_finished: Callable[[str, int], None] = field(default=lambda handle, code: None)
```

- [ ] **Step 2: Run all tests to verify no regressions**

Run: `conda run -n dagi python -m pytest tests/ -x -q --timeout=30`
Expected: All existing tests still PASS

- [ ] **Step 3: Commit**

```bash
git add agent/_loop_config.py
git commit -m "feat: add on_bg_started/output/finished callbacks to AgentCallbacks"
```

---

### Task 8: Wire PySide6 bridge signals

**Files:**
- Modify: `pyside_gui/bridge.py`

- [ ] **Step 1: Add the three new signals to `AgentBridge`**

In `pyside_gui/bridge.py`, after the `message_board_post` signal declaration (line 51), add:

```python
    bg_started = Signal(str, str)     # handle_id, command
    bg_output = Signal(str, str)      # handle_id, line
    bg_finished = Signal(str, int)    # handle_id, exit_code
```

- [ ] **Step 2: Wire the callbacks in `build_callbacks`**

In the `build_callbacks` method, before the `return AgentCallbacks(...)` call, add these closures:

```python
        def on_bg_started(handle: str, command: str) -> None:
            self.bg_started.emit(handle, command)

        def on_bg_output(handle: str, line: str) -> None:
            self.bg_output.emit(handle, line)

        def on_bg_finished(handle: str, exit_code: int) -> None:
            self.bg_finished.emit(handle, exit_code)
```

Then add the three fields to the `AgentCallbacks(...)` constructor call:

```python
            on_bg_started=on_bg_started,
            on_bg_output=on_bg_output,
            on_bg_finished=on_bg_finished,
```

- [ ] **Step 3: Commit**

```bash
git add pyside_gui/bridge.py
git commit -m "feat: add bg_started/output/finished signals to AgentBridge"
```

---

### Task 9: `ProcessesView` sidebar widget

**Files:**
- Create: `pyside_gui/sidebars/processes_view.py`

- [ ] **Step 1: Create the processes view**

Create `pyside_gui/sidebars/processes_view.py`:

```python
"""pyside_gui/sidebars/processes_view.py — Live background process viewer."""
from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QPushButton,
)

_HEADER_CSS = """
QLabel#proc-header {
    color: #6c7086;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px 0 4px 0;
}
"""

_CARD_CSS = """
QWidget#proc-card {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
}
"""

_ACTIVE_BADGE = "color: #a6e3a1; font-size: 10px; font-weight: bold;"
_DONE_BADGE = "color: #6c7086; font-size: 10px; font-weight: bold;"

_TERM_FONT = QFont("Consolas", 9)
_TERM_FONT.setStyleHint(QFont.StyleHint.Monospace)

_TERM_CSS = """
QPlainTextEdit {
    background: #11111b;
    color: #cdd6f4;
    border: none;
    padding: 4px;
}
"""


class _ProcessCard(QWidget):
    """Compact card showing a background process's live output."""

    def __init__(self, handle: str, command: str) -> None:
        super().__init__()
        self.handle = handle
        self.setObjectName("proc-card")
        self.setStyleSheet(_CARD_CSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header row: handle + command + status badge
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)

        handle_label = QLabel(f"[{handle}]")
        handle_label.setStyleSheet("color: #89b4fa; font-size: 11px; font-weight: bold;")
        header_row.addWidget(handle_label)

        cmd_display = command if len(command) <= 40 else command[:37] + "..."
        cmd_label = QLabel(cmd_display)
        cmd_label.setStyleSheet("color: #a6adc8; font-size: 10px;")
        cmd_label.setToolTip(command)
        header_row.addWidget(cmd_label, stretch=1)

        self._badge = QLabel("RUNNING")
        self._badge.setStyleSheet(_ACTIVE_BADGE)
        header_row.addWidget(self._badge)

        layout.addLayout(header_row)

        # Output area
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(_TERM_FONT)
        self._output.setStyleSheet(_TERM_CSS)
        self._output.setMaximumBlockCount(2000)
        self._output.setMinimumHeight(120)
        self._output.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(self._output, stretch=1)

    def append_line(self, line: str) -> None:
        self._output.appendPlainText(line)
        # Auto-scroll to bottom
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._output.setTextCursor(cursor)

    def mark_finished(self, exit_code: int) -> None:
        label = f"EXIT {exit_code}"
        self._badge.setText(label)
        self._badge.setStyleSheet(_DONE_BADGE)


class ProcessesView(QWidget):
    """Sidebar view showing all background bash processes and their live output."""

    def __init__(self) -> None:
        super().__init__()
        self.setStyleSheet("background: #1e1e2e;")
        self._cards: dict[str, _ProcessCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QLabel("PROCESSES")
        header.setObjectName("proc-header")
        header.setStyleSheet(_HEADER_CSS)
        header.setContentsMargins(8, 8, 8, 4)
        outer.addWidget(header)

        # Empty state label
        self._empty_label = QLabel("No background processes")
        self._empty_label.setStyleSheet("color: #6c7086; font-size: 11px; padding: 16px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._empty_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: #1e1e2e; }"
        )
        self._scroll.viewport().setStyleSheet("background: #1e1e2e;")

        self._container = QWidget()
        self._container.setStyleSheet("background: #1e1e2e;")
        self._cards_layout = QVBoxLayout(self._container)
        self._cards_layout.setContentsMargins(8, 4, 8, 8)
        self._cards_layout.setSpacing(8)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, stretch=1)

    @Slot(str, str)
    def on_process_started(self, handle: str, command: str) -> None:
        card = _ProcessCard(handle, command)
        self._cards[handle] = card
        self._cards_layout.insertWidget(0, card)
        self._empty_label.setVisible(False)

    @Slot(str, str)
    def on_process_output(self, handle: str, line: str) -> None:
        card = self._cards.get(handle)
        if card is not None:
            card.append_line(line)

    @Slot(str, int)
    def on_process_finished(self, handle: str, exit_code: int) -> None:
        card = self._cards.get(handle)
        if card is not None:
            card.mark_finished(exit_code)
```

- [ ] **Step 2: Commit**

```bash
git add pyside_gui/sidebars/processes_view.py
git commit -m "feat: add ProcessesView sidebar widget for live background process output"
```

---

### Task 10: Integrate `ProcessesView` into the left sidebar

**Files:**
- Modify: `pyside_gui/sidebars/__init__.py`
- Modify: `pyside_gui/left_sidebar.py:14,22-23,98-107`

- [ ] **Step 1: Export `ProcessesView` from the sidebars package**

Edit `pyside_gui/sidebars/__init__.py` to become:

```python
from pyside_gui.sidebars.session_history import SessionHistoryView
from pyside_gui.sidebars.file_tree import FileTreeView
from pyside_gui.sidebars.file_viewer import FileViewerView
from pyside_gui.sidebars.message_board import MessageBoardView
from pyside_gui.sidebars.plan_view import PlanView
from pyside_gui.sidebars.processes_view import ProcessesView

__all__ = [
    "SessionHistoryView",
    "FileTreeView",
    "FileViewerView",
    "MessageBoardView",
    "PlanView",
    "ProcessesView",
]
```

- [ ] **Step 2: Add the tab to `LeftSidebar`**

In `pyside_gui/left_sidebar.py`, make these edits:

1. Update the import to include `ProcessesView`:

```python
from pyside_gui.sidebars import (
    FileTreeView,
    FileViewerView,
    MessageBoardView,
    PlanView,
    ProcessesView,
    SessionHistoryView,
)
```

2. Add `"processes"` to `_VIEW_NAMES` and a terminal icon to `_RAIL_ICONS`:

```python
_VIEW_NAMES = ("history", "files", "viewer", "plan", "board", "processes")
_RAIL_ICONS = ("\U0001f4cb", "\U0001f4c1", "\U0001f4c4", "\U0001f4dd", "\U0001f4e2", "\U0001f5a5")
```

(`\U0001f5a5` is the desktop computer / monitor emoji — a reasonable icon for terminal processes.)

3. In `__init__`, after instantiating `self._board_view` and adding it to the panel, add:

```python
        self._processes_view = ProcessesView()
        self._panel.addWidget(self._processes_view)
```

- [ ] **Step 3: Add a `processes_view` property accessor**

After the existing `board_view` property in `LeftSidebar`, add:

```python
    @property
    def processes_view(self) -> ProcessesView:
        return self._processes_view
```

- [ ] **Step 4: Commit**

```bash
git add pyside_gui/sidebars/__init__.py pyside_gui/left_sidebar.py
git commit -m "feat: add Processes tab to PySide6 left sidebar"
```

---

### Task 11: Connect bridge signals to `ProcessesView` in the main window

**Files:**
- Modify: `pyside_gui/app.py`

- [ ] **Step 1: Find the `_connect_signals` method and add connections**

In `pyside_gui/app.py`, locate the `_connect_signals` method (where other bridge signals are connected to UI slots). Add these three connections:

```python
        self._bridge.bg_started.connect(self._left_sidebar.processes_view.on_process_started)
        self._bridge.bg_output.connect(self._left_sidebar.processes_view.on_process_output)
        self._bridge.bg_finished.connect(self._left_sidebar.processes_view.on_process_finished)
```

- [ ] **Step 2: Auto-open the processes tab when a process starts**

Also in `_connect_signals`, add a connection that auto-opens the processes sidebar tab when a background process starts:

```python
        self._bridge.bg_started.connect(
            lambda h, c: self._left_sidebar.activate_view("processes")
        )
```

- [ ] **Step 3: Launch the PySide6 GUI and verify**

Run: `conda run -n dagi python pyside_gui.py`

1. Start a session and ask the agent to run a long command with `bash_start`
2. Verify the Processes tab auto-opens in the left sidebar
3. Verify live stdout streams into the card
4. Verify the badge changes from RUNNING to EXIT when the process finishes

- [ ] **Step 4: Commit**

```bash
git add pyside_gui/app.py
git commit -m "feat: wire bridge signals to ProcessesView in main window"
```

---

### Task 12: Update `README.md` and `TODO.md`

**Files:**
- Modify: `README.md`
- Modify: `TODO.md`

- [ ] **Step 1: Update `README.md`**

Add a section or bullet under the tools / features area describing async bash:

- `bash_start` — launch a long-running command in the background, returns a handle
- `bash_status` — poll the latest stdout from a background command
- `bash_kill` — terminate a background command
- Processes tab in the PySide6 sidebar shows live output

- [ ] **Step 2: Update `TODO.md`**

Mark async bash as complete if it was listed, or add it to the completed section.

- [ ] **Step 3: Commit**

```bash
git add README.md TODO.md
git commit -m "docs: document async bash tools and processes sidebar"
```

---
