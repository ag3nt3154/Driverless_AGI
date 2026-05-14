"""tools/_terminal_subagent.py — Spawn a typed subagent terminal via file-based IPC.

All in-process subagents (web_research, explore_files, worker, review, etc.) delegate
through this module instead of running AgentLoop directly. The terminal shows live
agent output; the parent gets the result back via IpcChannel once the task completes.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from agent.ipc import IpcChannel, IpcTimeoutError

if TYPE_CHECKING:
    pass

_DAGI_ROOT = Path(__file__).parent.parent
_CLI_PATH = _DAGI_ROOT / "cli.py"

_POLL_INTERVAL = 5.0   # seconds between spinner refreshes while waiting for result
_READY_TIMEOUT = 60.0  # seconds to wait for subagent terminal to start


def spawn_terminal_subagent(
    subagent_type: str,
    task: str,
    project_path: Path,
    timeout: int | None = None,
    ready_timeout: float = _READY_TIMEOUT,
) -> str:
    """Spawn a typed subagent terminal, send one task, and return the result string.

    The terminal persists for 5 minutes after writing its result (managed by the
    subprocess itself). This function returns as soon as the result file appears —
    it does NOT wait for the terminal window to close.

    Args:
        subagent_type: Type name matching a .dagi/subagents/<type>/ directory.
        task:          The task prompt to send.
        project_path:  Project root; passed via --project so the subprocess resolves
                       config.yaml and tool allowed_roots correctly.
        timeout:       Seconds to wait for the result, or None to wait indefinitely.
        ready_timeout: Seconds to wait for the terminal to signal readiness.

    Returns:
        The final assistant text extracted by the subprocess.

    Raises:
        RuntimeError: If the terminal does not start within ready_timeout, or if the
                      task does not complete within timeout.
    """
    subagent_id = uuid.uuid4().hex[:8]
    ipc_dir = Path(tempfile.gettempdir()) / "dagi_ipc" / subagent_id
    ipc = IpcChannel(ipc_dir)

    argv = _build_argv(subagent_type, str(ipc_dir), str(project_path))
    subprocess.Popen(
        argv,
        creationflags=(
            subprocess.CREATE_NEW_CONSOLE
            | subprocess.CREATE_NEW_PROCESS_GROUP
        ),
    )

    try:
        ipc.poll_ready(timeout=ready_timeout)
    except IpcTimeoutError:
        raise RuntimeError(
            f"[{subagent_type}] Subagent terminal did not become ready within "
            f"{ready_timeout:.0f}s. Check that cli.py starts correctly."
        )

    ipc.write_task(seq=1, task=task)

    result_data = _poll_with_spinner(ipc, subagent_type, seq=1, timeout=timeout)

    if result_data.get("status") == "error":
        return f"[{subagent_type} error] {result_data.get('error', '')}"
    return result_data.get("result", "")


def _build_argv(
    subagent_type: str,
    ipc_dir: str,
    project_path: str,
) -> list[str]:
    return [
        sys.executable, str(_CLI_PATH),
        "--subagent-ipc-dir", ipc_dir,
        "--subagent-type", subagent_type,
        "--project", project_path,
        "--sync",   # force sync mode so the terminal renders tool calls line-by-line
    ]


def _poll_with_spinner(
    ipc: IpcChannel,
    subagent_type: str,
    seq: int,
    timeout: int | None,
) -> dict:
    """Poll for the IPC result while the subagent runs.

    When timeout is None, polls indefinitely in _POLL_INTERVAL chunks until a
    result appears — no deadline is set.  When timeout is an integer, raises
    IpcTimeoutError if the deadline is exceeded.
    """
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IpcTimeoutError(f"Timeout after {timeout}s")
            poll_timeout = min(_POLL_INTERVAL, remaining)
        else:
            poll_timeout = _POLL_INTERVAL  # poll in chunks, yield to OS
        try:
            return ipc.poll_result(seq, timeout=poll_timeout)
        except IpcTimeoutError:
            continue
