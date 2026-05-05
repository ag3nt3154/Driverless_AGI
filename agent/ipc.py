"""agent/ipc.py — File-based IPC channel for CLI subagent terminals.

Layout inside ipc_dir/:
    ready              zero-byte sentinel; subagent writes when it is polling
    task_<n>.json      parent writes: {"seq": n, "task": str}
    result_<n>.json    subagent writes: {"seq": n, "status": "ok"|"error",
                                         "result": str, "error": str}
    exit               zero-byte sentinel; parent writes to stop the subagent
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class IpcTimeoutError(TimeoutError):
    pass


class IpcChannel:
    """File-based IPC between the main agent (parent) and a subagent terminal."""

    def __init__(self, ipc_dir: Path) -> None:
        self.ipc_dir = Path(ipc_dir)
        self.ipc_dir.mkdir(parents=True, exist_ok=True)

    # ── Parent-side writes ────────────────────────────────────────────────────

    def write_task(self, seq: int, task: str) -> None:
        """Write a task message for the subagent to pick up."""
        payload = json.dumps({"seq": seq, "task": task})
        target = self.ipc_dir / f"task_{seq}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.rename(target)  # atomic on NTFS — reader never sees a partial write

    def write_exit(self) -> None:
        """Signal the subagent to shut down after its current task."""
        (self.ipc_dir / "exit").touch()

    # ── Subagent-side writes ──────────────────────────────────────────────────

    def write_ready(self) -> None:
        """Signal the parent that this subagent is alive and polling."""
        (self.ipc_dir / "ready").touch()

    def write_result(
        self,
        seq: int,
        *,
        status: str,
        result: str = "",
        error: str = "",
    ) -> None:
        """Write a result message for the parent to pick up."""
        payload = json.dumps({"seq": seq, "status": status,
                              "result": result, "error": error})
        target = self.ipc_dir / f"result_{seq}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.rename(target)

    # ── Polling helpers ───────────────────────────────────────────────────────

    def poll_ready(self, timeout: float = 30.0, poll_interval: float = 0.2) -> bool:
        """Block until the subagent writes the ready sentinel.

        Raises IpcTimeoutError if it does not appear within *timeout* seconds.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (self.ipc_dir / "ready").exists():
                return True
            time.sleep(poll_interval)
        raise IpcTimeoutError(f"Subagent did not signal ready within {timeout}s")

    def poll_task(
        self,
        seq: int,
        poll_interval: float = 0.2,
        timeout: float | None = None,
    ) -> dict | None:
        """Block until task_<seq>.json appears or the exit sentinel is written.

        Returns the parsed task dict, or None if the exit sentinel appeared first.
        Raises IpcTimeoutError if *timeout* is set and expires before either file.
        """
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        while True:
            if (self.ipc_dir / "exit").exists():
                return None
            task_file = self.ipc_dir / f"task_{seq}.json"
            if task_file.exists():
                return json.loads(task_file.read_text(encoding="utf-8"))
            if deadline is not None and time.monotonic() >= deadline:
                raise IpcTimeoutError(f"No task_{seq}.json within {timeout}s")
            time.sleep(poll_interval)

    def poll_result(
        self,
        seq: int,
        poll_interval: float = 0.2,
        timeout: float = 300.0,
    ) -> dict:
        """Block until result_<seq>.json appears.

        Raises IpcTimeoutError if it does not appear within *timeout* seconds.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result_file = self.ipc_dir / f"result_{seq}.json"
            if result_file.exists():
                return json.loads(result_file.read_text(encoding="utf-8"))
            time.sleep(poll_interval)
        raise IpcTimeoutError(f"No result_{seq}.json within {timeout}s")
