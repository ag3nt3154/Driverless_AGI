"""tools/_subagent_runner.py — Spawn a typed subagent as a piped subprocess.

The subagent runs cli.py with --subagent-type, --task-file, and --handoff flags.
Stdout is streamed as newline-delimited JSON events relayed to the parent TUI.
The parent polls the process PID until exit or timeout; a separate resume_subagent()
call can extend the wait without losing the process handle.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent import DAGI_ROOT as _DAGI_ROOT
_CLI_PATH = _DAGI_ROOT / "cli.py"
_POLL_INTERVAL = 2.0  # seconds between PID-alive checks


@dataclass
class _SubagentState:
    proc: subprocess.Popen
    handoff_path: Path
    subagent_type: str
    on_event: Callable[[str], None] | None


_active: dict[int, _SubagentState] = {}
_active_lock = threading.Lock()


def _stream_stdout(proc: subprocess.Popen, on_event: Callable[[str], None]) -> None:
    """Read stdout lines and relay each to on_event (runs in a daemon thread)."""
    try:
        for raw in proc.stdout:  # type: ignore[union-attr]
            line = raw.rstrip("\n")
            if line:
                on_event(line)
    except Exception:
        pass


def _poll_until(
    state: _SubagentState,
    extra_seconds: float,
) -> dict:
    """Poll proc until it exits or extra_seconds elapses.

    Returns:
        {"status": "ok",      "handoff": str}   — done, handoff written
        {"status": "timeout", "pid": int}        — still alive, deadline expired
        {"status": "error",   "message": str}    — exited without writing handoff
    """
    import time

    deadline = time.monotonic() + extra_seconds
    proc = state.proc

    while True:
        ret = proc.poll()
        if ret is not None:
            with _active_lock:
                _active.pop(proc.pid, None)
            if state.handoff_path.exists():
                return {"status": "ok", "handoff": str(state.handoff_path)}
            return {
                "status": "error",
                "message": f"subagent exited (code {ret}) without writing handoff",
            }
        if time.monotonic() >= deadline:
            return {"status": "timeout", "pid": proc.pid}
        time.sleep(_POLL_INTERVAL)


def run_subagent(
    subagent_type: str,
    task: str,
    project_path: Path,
    handoff_path: Path,
    timeout: float = 300.0,
    on_event: Callable[[str], None] | None = None,
) -> dict:
    """Spawn a subagent subprocess and block until exit or timeout.

    Leaves the proc in _active on timeout so resume_subagent() can continue polling.

    Returns:
        {"status": "ok",      "handoff": str}   — done
        {"status": "timeout", "pid": int}        — timed out, proc still alive
        {"status": "error",   "message": str}    — proc exited, no handoff
    """
    task_file = Path(tempfile.mktemp(suffix=".txt", prefix="dagi_task_"))
    task_file.write_text(task, encoding="utf-8")
    handoff_path.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        sys.executable, str(_CLI_PATH),
        "--subagent-type", subagent_type,
        "--task-file", str(task_file),
        "--handoff", str(handoff_path),
        "--project", str(project_path),
    ]

    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    state = _SubagentState(
        proc=proc,
        handoff_path=handoff_path,
        subagent_type=subagent_type,
        on_event=on_event,
    )
    with _active_lock:
        _active[proc.pid] = state

    if on_event:
        t = threading.Thread(target=_stream_stdout, args=(proc, on_event), daemon=True)
        t.start()

    result = _poll_until(state, timeout)
    if result["status"] != "timeout":
        task_file.unlink(missing_ok=True)
    return result


def resume_subagent(pid: int, extra_seconds: float) -> dict:
    """Resume polling an in-flight subagent after a timeout.

    Returns the same dict shape as run_subagent().
    """
    with _active_lock:
        state = _active.get(pid)
    if state is None:
        return {"status": "error", "message": f"No active subagent with PID {pid}"}
    return _poll_until(state, extra_seconds)
