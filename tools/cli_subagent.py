"""tools/cli_subagent.py — Spawn a custom dagi subagent terminal with a caller-supplied system prompt.

This is the escape hatch for cases where no predefined subagent type fits.
The parent agent provides a system_prompt at call time; the subagent runs
with the full tool registry (read, write, edit, bash, grep, find, web).

Prefer predefined spawn_*_subagent tools when the task fits a known role.
"""
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
    prompt_file: Path | None
    seq: int = 0
    alive: bool = True


class SpawnCliSubagentTool(BaseTool):
    """Spawn a custom dagi subagent terminal with a caller-defined system prompt.

    Use this only when no predefined subagent type (web_research, explore_files,
    review, worker) fits the task. The subagent receives the full tool registry.
    """

    name = "spawn_cli_subagent"
    description = (
        "Spawn a custom subagent terminal with a caller-supplied system prompt and full tool access. "
        "Use ONLY when no predefined subagent type fits the task — prefer spawn_web_research_subagent, "
        "spawn_explore_files_subagent, spawn_review_subagent, or spawn_worker_subagent instead. "
        "Set persistent=true to keep the terminal alive for follow-up tasks "
        "(capture the returned subagent_id and pass it in the next call)."
    )
    _parameters: dict = {
        "type": "object",
        "properties": {
            "system_prompt": {
                "type": "string",
                "description": "System prompt that defines the subagent's role and constraints.",
            },
            "task": {
                "type": "string",
                "description": "The initial task or query to send to the subagent.",
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
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait for a response. Default: 300.",
            },
        },
        "required": ["system_prompt", "task"],
    }

    # Class-level registry so handles survive across tool calls in one session
    _active: dict[str, _Handle] = {}

    def __init__(self, project_path: Path) -> None:
        self._project_path = project_path
        atexit.register(self._cleanup_all)

    def run(
        self,
        system_prompt: str,
        task: str,
        subagent_id: str | None = None,
        persistent: bool = False,
        timeout: int = 300,
    ) -> str:
        # ── Reuse or spawn ────────────────────────────────────────────────────
        if subagent_id and subagent_id in self._active:
            handle = self._active[subagent_id]
            if not handle.alive or handle.proc.poll() is not None:
                handle.alive = False
                return (
                    f"[spawn_cli_subagent error] Subagent {subagent_id!r} is no longer alive. "
                    "Omit subagent_id to spawn a new one."
                )
        else:
            subagent_id = uuid.uuid4().hex[:8]
            ipc_dir = Path(tempfile.gettempdir()) / "dagi_ipc" / subagent_id
            ipc = IpcChannel(ipc_dir)

            prompt_file = self._write_prompt_file(system_prompt, subagent_id)
            argv = self._build_argv(str(ipc_dir), str(prompt_file))
            proc = subprocess.Popen(
                argv,
                creationflags=(
                    subprocess.CREATE_NEW_CONSOLE
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                ),
            )
            handle = _Handle(
                subagent_id=subagent_id, ipc=ipc, proc=proc, prompt_file=prompt_file
            )
            self._active[subagent_id] = handle

            try:
                handle.ipc.poll_ready(timeout=60.0)
            except IpcTimeoutError:
                handle.alive = False
                proc.terminate()
                self._delete_prompt_file(handle)
                return (
                    f"[spawn_cli_subagent error] Subagent {subagent_id!r} did not become ready "
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
                f"[spawn_cli_subagent error] Timeout after {timeout}s waiting for result "
                f"(subagent_id: {subagent_id}, seq: {seq})"
            )

        result_text = result_data.get("result", "")
        if result_data.get("status") == "error":
            result_text = f"[spawn_cli_subagent error] {result_data.get('error', result_text)}"

        # ── Persist or close ──────────────────────────────────────────────────
        if not persistent:
            handle.ipc.write_exit()
            try:
                handle.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                handle.proc.terminate()
            handle.alive = False
            self._delete_prompt_file(handle)
            del self._active[subagent_id]
            return result_text

        return f"[subagent_id: {subagent_id}]\n\n{result_text}"

    def _write_prompt_file(self, system_prompt: str, subagent_id: str) -> Path:
        prompt_file = Path(tempfile.gettempdir()) / f"dagi_prompt_{subagent_id}.txt"
        prompt_file.write_text(system_prompt, encoding="utf-8")
        return prompt_file

    def _delete_prompt_file(self, handle: _Handle) -> None:
        if handle.prompt_file and handle.prompt_file.exists():
            try:
                handle.prompt_file.unlink()
            except OSError:
                pass

    def _build_argv(self, ipc_dir: str, prompt_file: str) -> list[str]:
        return [
            sys.executable, str(_CLI_PATH),
            "--subagent-ipc-dir", ipc_dir,
            "--subagent-type", "custom",
            "--system-prompt-file", prompt_file,
            "--project", str(self._project_path),
            "--sync",
        ]

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
            self._delete_prompt_file(handle)
        self._active.clear()
