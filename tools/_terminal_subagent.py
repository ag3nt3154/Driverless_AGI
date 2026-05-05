"""tools/_terminal_subagent.py — Spawn a typed subagent terminal via file-based IPC.

All in-process subagents (web_research, explore_files, plan) delegate through this
module instead of running AgentLoop directly. The terminal shows live agent output;
the parent gets the result back via IpcChannel once the task completes.
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
    plan_file: Path | None = None,
    timeout: int = 300,
    ready_timeout: float = _READY_TIMEOUT,
) -> str:
    """Spawn a typed subagent terminal, send one task, and return the result string.

    The terminal persists for 5 minutes after writing its result (managed by the
    subprocess itself). This function returns as soon as the result file appears —
    it does NOT wait for the terminal window to close.

    Args:
        subagent_type: One of "web_research", "explore_files", "plan".
        task:          The task prompt to send.
        project_path:  Project root; passed via --project so the subprocess resolves
                       config.yaml and tool allowed_roots correctly.
        plan_file:     Required for subagent_type="plan"; path of the plan file the
                       subagent is allowed to write.
        timeout:       Seconds to wait for the result (default 300; use 600 for plan).
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

    argv = _build_argv(subagent_type, str(ipc_dir), str(project_path), plan_file)
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
    plan_file: Path | None,
) -> list[str]:
    argv = [
        sys.executable, str(_CLI_PATH),
        "--subagent-ipc-dir", ipc_dir,
        "--subagent-type", subagent_type,
        "--project", project_path,
        "--sync",   # force sync mode so the terminal renders tool calls line-by-line
    ]
    if plan_file is not None:
        argv += ["--plan-file", str(plan_file)]
    return argv


def _poll_with_spinner(
    ipc: IpcChannel,
    subagent_type: str,
    seq: int,
    timeout: int,
) -> dict:
    """Poll for the IPC result while showing a Rich live spinner in the parent terminal."""
    try:
        from rich.console import Console
        from rich.live import Live
        from rich.spinner import Spinner

        console = Console()
        t0 = time.monotonic()
        deadline = t0 + timeout

        with Live(console=console, refresh_per_second=4) as live:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise IpcTimeoutError(f"Timeout after {timeout}s")
                elapsed = int(time.monotonic() - t0)
                live.update(
                    Spinner("dots", text=f"  [dim]{subagent_type} subagent running… {elapsed}s[/dim]")
                )
                try:
                    return ipc.poll_result(seq, timeout=min(_POLL_INTERVAL, remaining))
                except IpcTimeoutError:
                    continue  # update spinner and retry

    except ImportError:
        # Fallback if Rich is not available
        return ipc.poll_result(seq, timeout=float(timeout))
