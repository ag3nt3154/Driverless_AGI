"""tools/cli_subagent.py — Spawn a custom dagi subagent with a caller-supplied system prompt.

This is the escape hatch for cases where no predefined subagent type fits.
The parent agent provides a system_prompt at call time; the subagent runs
with the full tool registry (read, write, edit, bash, grep, find, web).

Prefer predefined spawn_*_subagent tools when the task fits a known role.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from agent.base_tool import BaseTool

from agent import DAGI_ROOT as _DAGI_ROOT  # noqa: F401 (kept for module-level symmetry)

if TYPE_CHECKING:
    from agent.session import SessionTracker


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
            "briefing": {
                "type": "string",
                "description": (
                    "Additional guidance from the main agent: traps to avoid, prior "
                    "failed attempt context, or extra constraints. Optional."
                ),
            },
            "handoff_spec": {
                "type": "string",
                "description": (
                    "Free-text description of what the parent wants in the handoff "
                    "report. Optional."
                ),
            },
        },
        "required": ["system_prompt", "task"],
    }

    def __init__(
        self,
        project_path: Path,
        on_event_factory: Callable[[str], Callable[[str], None]] | None = None,
        tracker: "SessionTracker | None" = None,
    ) -> None:
        self._project_path = project_path
        self._on_event_factory = on_event_factory
        self._tracker = tracker

    def run(
        self,
        system_prompt: str,
        task: str,
        timeout: int = 300,
    ) -> str:
        from tools._handoff_format import format_handoff_result
        from tools._subagent_runner import run_subagent

        subagent_id = uuid4().hex[:8]

        fd, _tmp = tempfile.mkstemp(suffix=".txt", prefix="dagi_prompt_")
        os.close(fd)
        prompt_file = Path(_tmp)
        prompt_file.write_text(system_prompt, encoding="utf-8")

        handoffs_dir = self._project_path / ".dagi" / "handoffs"
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        handoff_path = handoffs_dir / f"custom_{subagent_id}.md"

        on_event = self._on_event_factory("custom") if self._on_event_factory else None
        if on_event:
            on_event(json.dumps({"type": "start", "subagent_type": "custom"}))

        depth = self._tracker._depth if self._tracker else 0
        if self._tracker:
            self._tracker.record_subagent_start(subagent_id, "custom", task, depth)

        try:
            result = run_subagent(
                subagent_type="custom",
                task=task,
                project_path=self._project_path,
                handoff_path=handoff_path,
                timeout=float(timeout),
                on_event=on_event,
                extra_argv=["--system-prompt-file", str(prompt_file)],
            )
        finally:
            prompt_file.unlink(missing_ok=True)

        if self._tracker:
            self._tracker.record_subagent_end(subagent_id, str(result), depth)

        if result["status"] == "ok":
            return format_handoff_result(result["handoff"])
        if result["status"] == "ok_unverified":
            return format_handoff_result(result["handoff"], unverified=True)
        if result["status"] == "timeout":
            return json.dumps({"status": "timeout", "pid": result["pid"]})
        return f"[spawn_cli_subagent error] {result.get('message', 'unknown error')}"
