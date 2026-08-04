# .dagi/subagents/review/main.py
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker

_REVIEW_UTILS_PATH = Path(__file__).parent / "review_utils.py"

# Load review_utils once at import time; re-executing spec.loader.exec_module per run() is wasteful.
_spec = importlib.util.spec_from_file_location("_review_utils", _REVIEW_UTILS_PATH)
_review_utils_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_review_utils_mod)  # type: ignore[union-attr]


def _load_plan_text(config: "AgentConfig") -> str:
    for attr in ("active_plan_file", "plan_file"):
        p = getattr(config, attr, None)
        if p is not None:
            try:
                return Path(p).read_text(encoding="utf-8")
            except (FileNotFoundError, OSError):
                pass
    return ""


class SpawnReviewSubagentTool(BaseTool):
    name = "spawn_review_subagent"
    description = (
        "Review a worker's implementation against the plan's subtask "
        "requirements. Reads the worker handoff and runs tests."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "subtask_name": {
                "type": "string",
                "description": "Name of the subtask being reviewed.",
            },
            "worker_handoff_path": {
                "type": "string",
                "description": "Path to the worker's handoff report.",
            },
            "unit_test_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths to unit test files.",
            },
            "custom_instructions": {
                "type": "string",
                "description": "Additional review guidance. Optional.",
            },
        },
        "required": ["subtask_name", "worker_handoff_path", "unit_test_paths"],
    }

    def __init__(
        self,
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        tracker: "SessionTracker | None" = None,
    ) -> None:
        self._config = config
        self._callbacks = callbacks
        self._tracker = tracker

    def run(
        self,
        subtask_name: str,
        worker_handoff_path: str,
        unit_test_paths: list[str] | str = "",
        custom_instructions: str = "",
    ) -> str:
        from tools._handoff_format import dispatch_status_result, format_handoff_result

        if isinstance(unit_test_paths, str):
            unit_test_paths = [unit_test_paths] if unit_test_paths else []

        plan_text = _load_plan_text(self._config)
        task_body = _review_utils_mod.compose_review_task(
            plan_text, subtask_name, worker_handoff_path, unit_test_paths,
        )

        on_event = None
        if self._callbacks and self._callbacks.on_subagent_event_factory:
            on_event = self._callbacks.on_subagent_event_factory("review")

        result = _subagent_api.run_subagent(
            task=task_body,
            preset="review",
            custom_instructions=custom_instructions,
            project_path=self._config.project_path,
            on_event=on_event,
        )

        if result.is_ok:
            unverified = result.status == "ok_unverified"
            return format_handoff_result(str(result.handoff_path), unverified=unverified)
        return dispatch_status_result(
            {
                "status": result.status,
                "pid": result.pid,
                "escalation": result.escalation,
                "message": result.escalation or "",
            },
            "review",
            include_escalation=True,
        )
