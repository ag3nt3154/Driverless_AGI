"""tools/cli_subagent.py — Spawn a dagi agent via ConPTY and control it from the main agent."""
from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from agent.base_tool import BaseTool
from agent.pty_channel import EXIT_CMD, PtyChannel, PtyTimeoutError

_DAGI_ROOT = Path(__file__).parent.parent
_CLI_PATH = _DAGI_ROOT / "cli.py"
_LOG_DIR = _DAGI_ROOT / ".dagi" / "subagent_logs"


@dataclass
class _Handle:
    subagent_id: str
    channel: PtyChannel
    log_file: Path
    alive: bool = True


class CliSubAgentTool(BaseTool):
    """Spawn a visible dagi subagent terminal via ConPTY and exchange tasks with it."""

    name = "cli_subagent"
    description = (
        "Spawn a new terminal window running a full dagi agent via ConPTY. "
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
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
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

        if subagent_id and subagent_id in self._active:
            handle = self._active[subagent_id]
            if not handle.alive or not handle.channel.isalive():
                handle.alive = False
                return (
                    f"[cli_subagent error] Subagent {subagent_id!r} is no longer alive. "
                    "Omit subagent_id to spawn a new one."
                )
        else:
            subagent_id = uuid.uuid4().hex[:8]
            log_file = _LOG_DIR / f"{subagent_id}.log"
            argv = self._build_argv(effective_model)
            channel = PtyChannel(argv=argv, log_file=log_file)
            handle = _Handle(subagent_id=subagent_id, channel=channel, log_file=log_file)
            self._active[subagent_id] = handle
            self._launch_viewer(log_file, subagent_id)

        handle.channel.write(task + "\n")

        try:
            result = handle.channel.read_until_sentinel(timeout=float(timeout))
        except PtyTimeoutError:
            handle.alive = False
            return f"[cli_subagent error] Timeout after {timeout}s (subagent_id: {subagent_id})"

        if not persistent:
            handle.channel.write(EXIT_CMD + "\n")
            handle.channel.terminate()
            handle.alive = False
            del self._active[subagent_id]
            return result

        return f"[subagent_id: {subagent_id}]\n\n{result}"

    def _build_argv(self, model: str | None) -> list[str]:
        conda_env = os.environ.get("CONDA_DEFAULT_ENV", "dagi")
        argv = [
            "conda", "run", "--no-capture-output", "-n", conda_env,
            "python", str(_CLI_PATH),
            "--subagent-mode",
            "--project", str(self._project_path),
        ]
        if model:
            argv += ["--model", model]
        return argv

    def _launch_viewer(self, log_file: Path, subagent_id: str) -> None:
        """Open a visible terminal window that tails the subagent log."""
        conda_env = os.environ.get("CONDA_DEFAULT_ENV", "dagi")
        viewer_cmd = (
            f'conda run --no-capture-output -n {conda_env} '
            f'python "{_CLI_PATH}" --pty-viewer "{log_file}"'
        )
        title = f"dagi-subagent-{subagent_id}"
        wt = shutil.which("wt")
        if wt:
            launch = [wt, "new-tab", "--title", title, "--", "cmd", "/k", viewer_cmd]
        else:
            launch = ["cmd", "/c", f'start "{title}" cmd /k {viewer_cmd}']
        subprocess.Popen(
            launch,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )

    def _cleanup_all(self) -> None:
        for handle in list(self._active.values()):
            if handle.alive:
                try:
                    handle.channel.write(EXIT_CMD + "\n")
                    handle.channel.terminate()
                except Exception:
                    pass
        self._active.clear()
