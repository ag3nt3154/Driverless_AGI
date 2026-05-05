"""tools/cli_subagent.py — Spawn a dagi subagent terminal and control it via file-based IPC."""
from __future__ import annotations

import atexit
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from agent.base_tool import BaseTool
from agent.ipc import IpcChannel, IpcTimeoutError

_DAGI_ROOT = Path(__file__).parent.parent
_CLI_PATH = _DAGI_ROOT / "cli.py"


@dataclass
class _Handle:
    subagent_id: str
    ipc: IpcChannel
    proc: subprocess.Popen
    seq: int = 0
    alive: bool = True


class CliSubAgentTool(BaseTool):
    """Spawn a visible dagi subagent terminal and exchange tasks with it via file-based IPC."""

    name = "cli_subagent"
    description = (
        "Spawn a new terminal window running a full dagi agent. "
        "Send it a task prompt and receive its final response. "
        "Set persistent=true to keep the terminal alive for follow-up tasks "
        "(capture the returned subagent_id and pass it in the next call). "
        "Set persistent=false (default) to close the terminal after the task completes."
    )
    _parameters: dict = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task prompt to send to the subagent terminal.",
            },
            "subagent_id": {
                "type": "string",
                "description": (
                    "ID of an existing persistent subagent terminal to reuse. "
                    "Omit to spawn a fresh terminal."
                ),
            },
            "persistent": {
                "type": "boolean",
                "description": (
                    "If true, the terminal stays open for follow-up tasks "
                    "(return value includes [subagent_id: ...]). "
                    "If false (default), the terminal closes when the task is done."
                ),
            },
            "model": {
                "type": "string",
                "description": "Optional model ID override for this subagent terminal.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait for a response. Default: 300.",
            },
        },
        "required": ["task"],
    }

    # Class-level registry so handles survive across tool calls in one session
    _active: dict[str, _Handle] = {}

    def __init__(self, project_path: Path, model: str | None = None) -> None:
        self._project_path = project_path
        self._model = model
        atexit.register(self._cleanup_all)

    def run(
        self,
        task: str,
        subagent_id: str | None = None,
        persistent: bool = False,
        model: str | None = None,
        timeout: int = 300,
    ) -> str:
        effective_model = model or self._model

        # ── Reuse or spawn ────────────────────────────────────────────────────
        if subagent_id and subagent_id in self._active:
            handle = self._active[subagent_id]
            if not handle.alive or handle.proc.poll() is not None:
                handle.alive = False
                return (
                    f"[cli_subagent error] Subagent {subagent_id!r} is no longer alive. "
                    "Omit subagent_id to spawn a new one."
                )
        else:
            subagent_id = uuid.uuid4().hex[:8]
            ipc_dir = Path(tempfile.gettempdir()) / "dagi_ipc" / subagent_id
            ipc = IpcChannel(ipc_dir)

            argv = self._build_argv(str(ipc_dir), effective_model)
            proc = subprocess.Popen(
                argv,
                creationflags=(
                    subprocess.CREATE_NEW_CONSOLE
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                ),
            )
            handle = _Handle(subagent_id=subagent_id, ipc=ipc, proc=proc)
            self._active[subagent_id] = handle

            # Wait for the subagent to signal it's ready to accept tasks
            try:
                handle.ipc.poll_ready(timeout=60.0)
            except IpcTimeoutError:
                handle.alive = False
                proc.terminate()
                return (
                    f"[cli_subagent error] Subagent {subagent_id!r} did not become ready "
                    "within 60s. Check that cli.py starts correctly."
                )

        # ── Send task ─────────────────────────────────────────────────────────
        handle.seq += 1
        seq = handle.seq
        handle.ipc.write_task(seq, task)

        # ── Wait for result ───────────────────────────────────────────────────
        try:
            result_data = handle.ipc.poll_result(seq, timeout=float(timeout))
        except IpcTimeoutError:
            handle.alive = False
            return (
                f"[cli_subagent error] Timeout after {timeout}s waiting for result "
                f"(subagent_id: {subagent_id}, seq: {seq})"
            )

        result_text = result_data.get("result", "")
        if result_data.get("status") == "error":
            result_text = f"[cli_subagent error] {result_data.get('error', result_text)}"

        # ── Persist or close ──────────────────────────────────────────────────
        if not persistent:
            handle.ipc.write_exit()
            try:
                handle.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                handle.proc.terminate()
            handle.alive = False
            del self._active[subagent_id]
            return result_text

        return f"[subagent_id: {subagent_id}]\n\n{result_text}"

    def _build_argv(self, ipc_dir: str, model: str | None) -> list[str]:
        # sys.executable is the real .exe for the active conda env — no shim needed.
        argv = [
            sys.executable, str(_CLI_PATH),
            "--subagent-ipc-dir", ipc_dir,
            "--project", str(self._project_path),
        ]
        if model:
            argv += ["--model", model]
        return argv

    def _cleanup_all(self) -> None:
        for handle in list(self._active.values()):
            if handle.alive:
                try:
                    handle.ipc.write_exit()
                    handle.proc.wait(timeout=5)
                except Exception:
                    try:
                        handle.proc.terminate()
                    except Exception:
                        pass
        self._active.clear()
