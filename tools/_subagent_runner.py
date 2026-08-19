"""tools/_subagent_runner.py — Spawn a typed subagent as a piped subprocess.

The subagent runs tools/subagent_main.py with --subagent-type, --task-file,
and --handoff flags. Stdout is streamed as newline-delimited JSON events
relayed to the parent TUI. The parent polls the process PID until exit or
timeout; a separate resume_subagent() call can extend the wait without
losing the process handle.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent import DAGI_ROOT as _DAGI_ROOT
from agent._process_kill import kill_process_tree
_POLL_INTERVAL = 2.0  # seconds between PID-alive checks


@dataclass
class _SubagentState:
    proc: subprocess.Popen
    handoff_path: Path
    task_file: Path
    subagent_type: str
    on_event: Callable[[str], None] | None
    fork_context_path: Path | None = None


_active: dict[int, _SubagentState] = {}
_active_lock = threading.Lock()


def owns_fork_context_path(path: Path) -> bool:
    """Return whether a registered subagent state owns the fork-context file."""
    with _active_lock:
        return any(state.fork_context_path == path for state in _active.values())


def _stream_stdout(proc: subprocess.Popen, on_event: Callable[[str], None]) -> None:
    """Read stdout lines and relay each to on_event (runs in a daemon thread)."""
    try:
        for raw in proc.stdout:  # type: ignore[union-attr]
            line = raw.rstrip("\n")
            if line:
                on_event(line)
    except Exception:
        pass


def _drain_stdout(proc: subprocess.Popen) -> None:
    """Read and discard stdout to prevent pipe buffer deadlock (no relay needed)."""
    try:
        for _ in proc.stdout:  # type: ignore[union-attr]
            pass
    except Exception:
        pass


def _check_unverified(handoff_path: Path) -> bool:
    """Return True if a sidecar '_unverified.flag' exists next to handoff_path.

    Written by tools/subagent_main.py when a handoff was scraped from the last
    assistant message (retry+degrade path) rather than deliberately reported.
    """
    from tools._handoff_format import unverified_flag_path

    return unverified_flag_path(handoff_path).exists()


def _handoff_result(handoff_path: Path) -> dict | None:
    """Build the ok/ok_unverified result dict for a written handoff, or None if absent."""
    if not handoff_path.exists():
        return None
    if _check_unverified(handoff_path):
        return {"status": "ok_unverified", "handoff": str(handoff_path)}
    return {"status": "ok", "handoff": str(handoff_path)}


def _cleanup_terminal_state(state: _SubagentState) -> None:
    """Release files and tracking owned by a terminal subprocess state."""
    with _active_lock:
        _active.pop(state.proc.pid, None)
    state.task_file.unlink(missing_ok=True)
    if state.fork_context_path is not None:
        state.fork_context_path.unlink(missing_ok=True)


def _poll_until(
    state: _SubagentState,
    extra_seconds: float,
) -> dict:
    """Poll proc until it exits, escalates, or extra_seconds elapses.

    Returns:
        {"status": "ok",            "handoff": str}   — done, handoff written
        {"status": "ok_unverified", "handoff": str}   — done, but handoff was scraped
                                                         from the last assistant message
                                                         after retry+degrade (see
                                                         tools/subagent_main.py), not a
                                                         deliberate structured report
        {"status": "escalated",     "escalation": str} — subagent raised a blocking issue
        {"status": "timeout",       "pid": int}        — still alive, deadline expired
        {"status": "error",         "message": str}    — exited without writing handoff,
                                                          or escalation file unreadable
    """
    import time

    deadline = time.monotonic() + extra_seconds
    proc = state.proc
    # Sidecar file written by tools/escalate_issue.py when a subagent needs help.
    escalation_path = state.handoff_path.with_name(
        state.handoff_path.stem + "_escalation.md"
    )

    while True:
        if escalation_path.exists():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Terminate didn't reap in time; force-kill. No proc.wait() follow-up
                # here — acceptable given process lifetime, but noted intentionally.
                proc.kill()
            _cleanup_terminal_state(state)
            try:
                content = escalation_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return {
                    "status": "error",
                    "message": f"escalation file present but unreadable: {exc}",
                }
            return {"status": "escalated", "escalation": content}

        ret = proc.poll()
        if ret is not None:
            _cleanup_terminal_state(state)
            handoff_result = _handoff_result(state.handoff_path)
            if handoff_result is not None:
                return handoff_result
            return {
                "status": "error",
                "message": f"subagent exited (code {ret}) without writing handoff",
            }
        if time.monotonic() >= deadline:
            return {"status": "timeout", "pid": proc.pid}
        time.sleep(_POLL_INTERVAL)


def force_kill_active_subagents() -> int:
    """Force-kill every currently in-flight subagent's process tree.

    Best-effort. Forced termination is terminal, so it also releases the
    state-owned task and fork-context files. Returns the number of processes killed.
    """
    with _active_lock:
        states = list(_active.values())
    killed = 0
    for state in states:
        kill_process_tree(state.proc)
        _cleanup_terminal_state(state)
        killed += 1
    return killed


def run_subagent(
    subagent_type: str,
    task: str,
    project_path: Path,
    handoff_path: Path,
    timeout: float = 1800.0,
    on_event: Callable[[str], None] | None = None,
    extra_argv: list[str] | None = None,
) -> dict:
    """Spawn a subagent subprocess and block until exit or timeout.

    Leaves the proc in _active on timeout so resume_subagent() can continue polling.

    Returns:
        {"status": "ok",      "handoff": str}   — done
        {"status": "timeout", "pid": int}        — timed out, proc still alive
        {"status": "error",   "message": str}    — proc exited, no handoff
    """
    fd, _tmp = tempfile.mkstemp(suffix=".txt", prefix="dagi_task_")
    os.close(fd)
    task_file = Path(_tmp)
    task_file.write_text(task, encoding="utf-8")
    handoff_path.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        sys.executable, "-m", "tools.subagent_main",
        "--subagent-type", subagent_type,
        "--task-file", str(task_file),
        "--handoff", str(handoff_path),
        "--project", str(project_path),
    ]
    if extra_argv:
        argv.extend(extra_argv)

    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        argv,
        cwd=str(_DAGI_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
        **popen_kwargs,
    )

    # Track fork-context path for cleanup on terminal paths
    fc_path: Path | None = None
    if extra_argv:
        try:
            idx = extra_argv.index("--fork-context")
            fc_path = Path(extra_argv[idx + 1])
        except (ValueError, IndexError):
            pass

    state = _SubagentState(
        proc=proc,
        handoff_path=handoff_path,
        task_file=task_file,
        subagent_type=subagent_type,
        on_event=on_event,
        fork_context_path=fc_path,
    )
    with _active_lock:
        _active[proc.pid] = state

    if on_event:
        t = threading.Thread(target=_stream_stdout, args=(proc, on_event), daemon=True)
    else:
        t = threading.Thread(target=_drain_stdout, args=(proc,), daemon=True)
    t.start()

    return _poll_until(state, timeout)


def resume_subagent(pid: int, extra_seconds: float) -> dict:
    """Resume polling an in-flight subagent after a timeout.

    Returns the same dict shape as run_subagent().
    """
    with _active_lock:
        state = _active.get(pid)
    if state is None:
        return {"status": "error", "message": f"No active subagent with PID {pid}"}
    return _poll_until(state, extra_seconds)
