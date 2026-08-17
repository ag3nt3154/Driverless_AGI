# .dagi/subagents/worker/main.py
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog

_PLAN_UTILS_PATH = Path(__file__).parent / "plan_utils.py"

# Load plan_utils once at import time; re-executing spec.loader.exec_module per run() is wasteful.
_spec = importlib.util.spec_from_file_location("_worker_plan_utils", _PLAN_UTILS_PATH)
_plan_utils_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_plan_utils_mod)  # type: ignore[union-attr]


class RunWorkerTool(BaseTool):
    name = "run_worker"
    description = (
        "Execute a single subtask with full tool access. Receives plan "
        "context and subtask details automatically. Writes a structured "
        "handoff report when done."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "subtask_name": {
                "type": "string",
                "description": (
                    "Name of the subtask to execute — must match the "
                    "heading in the plan."
                ),
            },
            "custom_instructions": {
                "type": "string",
                "description": (
                    "Additional guidance: traps to avoid, prior failed "
                    "attempt context, or extra constraints. Optional."
                ),
            },
        },
        "required": ["subtask_name"],
    }

    def __init__(
        self,
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        tracker: "SessionTracker | None" = None,
        session_log: "SessionLog | None" = None,
    ) -> None:
        self._config = config
        self._callbacks = callbacks
        self._tracker = tracker
        self._session_log = session_log

    def run(self, subtask_name: str, custom_instructions: str = "") -> str:
        from tools._handoff_format import (
            dispatch_status_result,
            format_handoff_result,
        )

        plan_text = _plan_utils_mod.load_plan_text(self._config)
        task_body = _plan_utils_mod.compose_worker_task(plan_text, subtask_name)

        on_event = None
        if self._callbacks and self._callbacks.on_subagent_event_factory:
            on_event = self._callbacks.on_subagent_event_factory("worker")

        result = _subagent_api.run_subagent(
            task=task_body,
            preset="worker",
            custom_instructions=custom_instructions,
            project_path=self._config.project_path,
            on_event=on_event,
            parent_log=self._session_log,
        )

        if result.is_ok:
            # handoff_text fast-path only for verified ok; unverified needs banner via format_handoff_result.
            unverified = result.status == "ok_unverified"
            if result.handoff_text and not unverified:
                return result.handoff_text
            return format_handoff_result(str(result.handoff_path), unverified=unverified)
        return dispatch_status_result(
            {
                "status": result.status,
                "pid": result.pid,
                "escalation": result.escalation,
                "message": result.escalation or "",
            },
            "worker",
            include_escalation=True,
        )
