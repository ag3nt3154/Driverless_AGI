"""tools/_subagent_runner.py — Spawn a typed subagent as a piped subprocess.

The subagent runs tools/subagent_main.py with --subagent-type, --task-file,
and --handoff flags. Stdout is streamed as newline-delimited JSON events
relayed to the parent TUI. The parent polls the process PID until exit or
timeout; a separate resume_subagent() call can extend the wait without
losing the process handle.

Output capture: every line is tee'd to a ring buffer (last ~32 KiB) and a
full UTF-8 log file beside the handoff. The buffer and log are populated
before _poll_until builds its result, guaranteed by joining the reader thread.
"""
from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent import DAGI_ROOT as _DAGI_ROOT
from agent._process_kill import kill_process_tree

_POLL_INTERVAL = 2.0       # seconds between PID-alive checks
_OUTPUT_MAXLINES = 400     # ring buffer: ~32 KiB at ~80 chars/line
_READER_JOIN_TIMEOUT = 5.0 # seconds to wait for reader thread on exit


@dataclass
class _SubagentState:
    proc: subprocess.Popen
    handoff_path: Path
    task_file: Path
    subagent_type: str
    on_event: Callable[[str], None] | None
    fork_context_path: Path | None = None
    output_buf: "collections.deque[str]" = field(
        default_factory=lambda: collections.deque(maxlen=_OUTPUT_MAXLINES)
    )
    total_output_ref: list = field(default_factory=lambda: [0])
    reader_thread: threading.Thread | None = None
    output_log_path: Path | None = None


_active: dict[int, _SubagentState] = {}
_active_lock = threading.Lock()


def owns_fork_context_path(path: Path) -> bool:
    """Return whether a registered subagent state owns the fork-context file."""
    with _active_lock:
        return any(state.fork_context_path == path for state in _active.values())


def _tee_stdout(
    proc: subprocess.Popen,
    on_event: Callable[[str], None] | None,
    buf: "collections.deque[str]",
    total_ref: list,
    log_path: Path,
) -> None:
    """Read stdout, relay to on_event, accumulate tail buffer, write full log.

    Runs in a daemon thread. The log file is opened synchronously and closed
    on EOF — callers that join this thread are guaranteed the log is complete.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
            for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.rstrip("\n")
                if line and on_event:
                    on_event(line)
                buf.append(line)
                total_ref[0] += 1
                lf.write(raw if raw.endswith("\n") else raw + "\n")
    except Exception:
        pass


def _check_unverified(handoff_path: Path) -> bool:
    """Return True if a sidecar '_unverified.flag' exists next to handoff_path."""
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


def _collect_output(state: _SubagentState) -> tuple[str, Path | None]:
    """Join reader thread and return (output_tail, output_log_path).

    Joins with a bounded timeout so a hung reader never stalls the result.
    Must be called after the process has exited.
    """
    if state.reader_thread is not None:
        state.reader_thread.join(timeout=_READER_JOIN_TIMEOUT)

    lines = list(state.output_buf)
    total = state.total_output_ref[0]
    tail = "\n".join(lines)
    truncated = total > len(lines)

    log_path = state.output_log_path
    log_exists = log_path is not None and log_path.exists() and log_path.stat().st_size > 0
    if truncated and tail and log_path:
        tail = f"[truncated — full log: {log_path}]\n...\n{tail}"
    return tail, (log_path if log_exists else None)


def _poll_until(
    state: _SubagentState,
    extra_seconds: float,
) -> dict:
    """Poll proc until it exits or extra_seconds elapses.

    Returns:
        {"status": "ok",            "handoff": str, ...diag}
        {"status": "ok_unverified", "handoff": str, ...diag}
        {"status": "timeout",       "pid": int}
        {"status": "error",         "message": str, "exit_code": int, ...diag}
    """
    import time

    deadline = time.monotonic() + extra_seconds
    proc = state.proc

    while True:
        ret = proc.poll()
        if ret is not None:
            output_tail, output_log = _collect_output(state)
            _cleanup_terminal_state(state)

            diag: dict = {
                "exit_code": ret,
                "output_tail": output_tail,
                "output_log_path": str(output_log) if output_log else None,
            }
            handoff_result = _handoff_result(state.handoff_path)
            if handoff_result is not None:
                return {**handoff_result, **diag}
            return {
                "status": "error",
                "message": f"subagent exited (code {ret}) without writing handoff",
                **diag,
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
        {"status": "ok",      "handoff": str, ...diag}
        {"status": "timeout", "pid": int}
        {"status": "error",   "message": str, "exit_code": int, ...diag}

    diag keys: exit_code (int|None), output_tail (str), output_log_path (str|None)
    """
    fd, _tmp = tempfile.mkstemp(suffix=".txt", prefix="dagi_task_")
    os.close(fd)
    task_file = Path(_tmp)
    task_file.write_text(task, encoding="utf-8")
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    output_log_path = handoff_path.with_suffix(".output.log")

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

    fc_path: Path | None = None
    if extra_argv:
        try:
            idx = extra_argv.index("--fork-context")
            fc_path = Path(extra_argv[idx + 1])
        except (ValueError, IndexError):
            pass

    buf: collections.deque[str] = collections.deque(maxlen=_OUTPUT_MAXLINES)
    total_ref: list[int] = [0]

    state = _SubagentState(
        proc=proc,
        handoff_path=handoff_path,
        task_file=task_file,
        subagent_type=subagent_type,
        on_event=on_event,
        fork_context_path=fc_path,
        output_buf=buf,
        total_output_ref=total_ref,
        output_log_path=output_log_path,
    )

    t = threading.Thread(
        target=_tee_stdout,
        args=(proc, on_event, buf, total_ref, output_log_path),
        daemon=True,
    )
    state.reader_thread = t
    t.start()

    with _active_lock:
        _active[proc.pid] = state

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
