"""tools/cli_subagent.py — Spawn a custom dagi subagent with a caller-supplied system prompt.

This is the escape hatch for cases where no predefined subagent type fits.
The parent agent provides a system_prompt at call time; the subagent runs
with the full tool registry (read, write, edit, bash, grep, find, web).

Prefer predefined spawn_*_subagent tools when the task fits a known role.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

from agent.base_tool import BaseTool

from agent import DAGI_ROOT as _DAGI_ROOT
_CLI_PATH = _DAGI_ROOT / "cli.py"


class SpawnCliSubagentTool(BaseTool):
    """Spawn a custom dagi subagent with a caller-defined system prompt and full tool access.

    Use ONLY when no predefined subagent type (web_research, explore_files,
    review, worker) fits the task.
    """

    name = "spawn_cli_subagent"
    description = (
        "Spawn a custom subagent with a caller-supplied system prompt and full tool access. "
        "Use ONLY when no predefined subagent type fits the task — prefer "
        "spawn_web_research_subagent, spawn_explore_files_subagent, "
        "spawn_review_subagent, or spawn_worker_subagent instead."
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
                "description": "The task or query to send to the subagent.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait for a response. Default: 300.",
            },
        },
        "required": ["system_prompt", "task"],
    }

    def __init__(self, project_path: Path) -> None:
        self._project_path = project_path

    def run(
        self,
        system_prompt: str,
        task: str,
        timeout: int = 300,
    ) -> str:
        import json
        from tools._subagent_runner import run_subagent

        subagent_id = uuid.uuid4().hex[:8]

        # Write system prompt and task to temp files
        fd, _tmp = tempfile.mkstemp(suffix=".txt", prefix="dagi_prompt_")
        os.close(fd)
        prompt_file = Path(_tmp)
        prompt_file.write_text(system_prompt, encoding="utf-8")

        fd, _tmp = tempfile.mkstemp(suffix=".txt", prefix="dagi_task_")
        os.close(fd)
        task_file = Path(_tmp)
        task_file.write_text(task, encoding="utf-8")

        handoffs_dir = self._project_path / ".dagi" / "handoffs"
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        handoff_path = handoffs_dir / f"custom_{subagent_id}.md"

        import subprocess
        argv = [
            sys.executable, str(_CLI_PATH),
            "--subagent-type", "custom",
            "--task-file", str(task_file),
            "--handoff", str(handoff_path),
            "--system-prompt-file", str(prompt_file),
            "--project", str(self._project_path),
        ]

        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

        try:
            proc.wait(timeout=float(timeout))
        except subprocess.TimeoutExpired:
            proc.terminate()
            return json.dumps({"status": "timeout", "pid": proc.pid})
        finally:
            prompt_file.unlink(missing_ok=True)
            task_file.unlink(missing_ok=True)

        if handoff_path.exists():
            return f"Subagent completed. Handoff written to: {handoff_path}"
        return "[spawn_cli_subagent error] subagent exited without writing handoff"
