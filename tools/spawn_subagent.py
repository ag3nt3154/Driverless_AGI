"""tools/spawn_subagent.py — Auto-discovered predefined subagent tool.

One SpawnSubagentTool instance is created per valid entry in .dagi/subagents/
(directories containing both prompt.md and config.yaml). The parent agent
selects the right type via tool name and description; the task parameter
carries the query or instruction.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker


class SpawnSubagentTool(BaseTool):
    """Parameterized tool for a single predefined subagent type."""

    # Schema is identical for all instances; name/description are instance-level.
    _parameters: dict = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task or query to send to the subagent.",
            },
        },
        "required": ["task"],
    }

    def __init__(
        self,
        type_name: str,
        description: str,
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        cwd: Path = Path("."),
        allowed_roots: list[Path] | None = None,
        tracker: "SessionTracker | None" = None,
    ) -> None:
        self.name = f"spawn_{type_name}_subagent"
        self.description = description
        self._type_name = type_name
        self._config = config
        self._tracker = tracker

    def run(self, task: str) -> str:
        try:
            from tools._terminal_subagent import spawn_terminal_subagent

            subagent_id = uuid4().hex[:8]
            depth = self._tracker._depth if self._tracker else 0

            if self._tracker:
                self._tracker.record_subagent_start(subagent_id, self._type_name, task, depth)

            result = spawn_terminal_subagent(
                subagent_type=self._type_name,
                task=task,
                project_path=self._config.project_path,
                timeout=300,
            )

            if self._tracker:
                self._tracker.record_subagent_end(subagent_id, result, depth)

            return result
        except Exception as e:
            return f"[{self._type_name} error] {e}"
