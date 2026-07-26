"""tools/spawn_subagent.py — Auto-discovered predefined subagent tool.

One SpawnSubagentTool instance is created per valid entry in .dagi/subagents/
(directories containing both prompt.md and subagent_config.yaml). The parent
agent selects the right type via tool name; the tool generates the handoff path
internally and returns it on success.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

import yaml

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentConfig
    from agent.session import SessionTracker

from agent import DAGI_ROOT as _DAGI_ROOT

_FALLBACK_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "The task or query to send to the subagent.",
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
    "required": ["task"],
}



def _load_plan_text(config: "AgentConfig") -> str:
    for attr in ("plan_file", "active_plan_file"):
        plan_path = getattr(config, attr, None)
        if plan_path is not None:
            try:
                return Path(plan_path).read_text(encoding="utf-8")
            except (FileNotFoundError, OSError):
                pass
    return ""


def _compose_worker_context(
    plan_text: str,
    subtask_name: str,
    briefing: str,
    handoff_file: str,
) -> str:
    from tools._plan_parser import extract_subtask

    subtask_ctx = extract_subtask(plan_text, subtask_name, include_tests=False) if plan_text else ""

    sections: list[str] = []
    if subtask_ctx:
        sections.append(f"## Subtask\n{subtask_ctx}")
    if briefing:
        sections.append(f"## Instructions\n{briefing}")
    sections.append(f"## Output\nWrite your handoff report to: {handoff_file}")

    return "\n\n---\n\n".join(sections)


def _compose_explore_context(task: str, handoff_file: str) -> str:
    sections: list[str] = [
        f"## Task\n{task}",
        f"## Output\nWrite your exploration report to: {handoff_file}",
    ]
    return "\n\n---\n\n".join(sections)


def _compose_review_context(
    plan_text: str,
    subtask_name: str,
    worker_handoff_path: str,
    unit_test_paths: list[str],
    review_file: str,
    briefing: str,
) -> str:
    from tools._plan_parser import extract_subtask

    subtask_ctx = extract_subtask(plan_text, subtask_name, include_tests=True) if plan_text else ""

    sections: list[str] = []
    if subtask_ctx:
        sections.append(f"## Subtask Being Reviewed\n{subtask_ctx}")
    if worker_handoff_path:
        sections.append(
            f"## Worker Handoff\n"
            f"The worker's implementation report is at: {worker_handoff_path}\n"
            f"Read it before evaluating the subtask."
        )
    if briefing:
        sections.append(f"## Instructions\n{briefing}")

    unit_test_list = "\n".join(unit_test_paths) if unit_test_paths else ""
    output_lines = []
    if unit_test_list:
        output_lines.append(f"Unit test paths:\n{unit_test_list}")
    output_lines.append(f"Write your review report to: {review_file}")
    sections.append("## Output\n" + "\n".join(output_lines))

    return "\n\n---\n\n".join(sections)


class SpawnSubagentTool(BaseTool):
    """Parameterized tool for a single predefined subagent type."""

    def __init__(
        self,
        type_name: str,
        description: str,
        config: "AgentConfig",
        on_event_factory: Callable[[str], Callable[[str], None]] | None = None,
        tracker: "SessionTracker | None" = None,
        timeout: float = 1800.0,
    ) -> None:
        self.name = f"spawn_{type_name}_subagent"
        self.description = description
        self._type_name = type_name
        self._config = config
        self._tracker = tracker
        self._on_event_factory = on_event_factory
        self._timeout = timeout
        self._parameters = self._load_parameters(type_name, config)

    @staticmethod
    def _load_parameters(type_name: str, config: "AgentConfig") -> dict:
        search_paths: list[Path] = [
            _DAGI_ROOT / ".dagi" / "subagents" / type_name / "subagent_config.yaml",
        ]
        proj = getattr(config, "project_path", None)
        if isinstance(proj, Path):
            search_paths.insert(
                0,
                proj / ".dagi" / "subagents" / type_name / "subagent_config.yaml",
            )
        for config_path in search_paths:
            try:
                data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                if "parameters" in data:
                    return data["parameters"]
            except (FileNotFoundError, OSError, yaml.YAMLError):
                pass
        return _FALLBACK_PARAMETERS

    def run(self, **kwargs) -> str:
        from tools._subagent_runner import run_subagent

        subagent_id = uuid4().hex[:8]
        active_plan = self._config.active_plan_file or self._config.plan_file
        if active_plan:
            handoffs_dir = Path(active_plan).parent  # .dagi/plans/plan_<ts>/
        else:
            handoffs_dir = self._config.project_path / ".dagi" / "handoffs"
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        handoff_path = handoffs_dir / f"{self._type_name}_{subagent_id}.md"

        on_event = self._on_event_factory(self._type_name) if self._on_event_factory else None
        if on_event:
            on_event(json.dumps({"type": "start", "subagent_type": self._type_name}))

        task = self._compose_task(handoff_path=handoff_path, **kwargs)

        depth = self._tracker._depth if self._tracker else 0
        if self._tracker:
            self._tracker.record_subagent_start(subagent_id, self._type_name, task, depth)

        result = run_subagent(
            subagent_type=self._type_name,
            task=task,
            project_path=self._config.project_path,
            handoff_path=handoff_path,
            timeout=self._timeout,
            on_event=on_event,
        )

        if self._tracker:
            self._tracker.record_subagent_end(subagent_id, str(result), depth)

        if result["status"] == "escalated":
            return f"[{self._type_name} escalated]\n\n{result['escalation']}"
        if result["status"] == "ok":
            return self._format_ok_result(result["handoff"])
        if result["status"] == "ok_unverified":
            return self._format_ok_result(result["handoff"], unverified=True)
        if result["status"] == "timeout":
            return json.dumps({"status": "timeout", "pid": result["pid"]})
        return f"[{self._type_name} error] {result.get('message', 'unknown error')}"

    @staticmethod
    def _format_ok_result(handoff_path: str, unverified: bool = False) -> str:
        """Inline the handoff file's content so the main agent always sees it
        without a separate `read` call — relying on the agent to remember to
        read the file is exactly what let handoffs go unread in practice.

        When `unverified` is True, the subagent never called `write_handoff` and
        the parent process scraped its last message into the handoff file instead.
        A warning banner is prepended so the caller doesn't mistake scraped,
        informal text for a deliberate structured report.

        Thin wrapper kept for backward compatibility (e.g. `extend_timeout`
        imports this staticmethod directly); the actual formatting lives in
        the shared `tools._handoff_format.format_handoff_result`."""
        from tools._handoff_format import format_handoff_result

        return format_handoff_result(handoff_path, unverified=unverified)

    def _compose_task(self, handoff_path: Path, **kwargs) -> str:
        plan_text = _load_plan_text(self._config)

        if self._type_name == "worker":
            return _compose_worker_context(
                plan_text=plan_text,
                subtask_name=kwargs.get("subtask_name", ""),
                briefing=kwargs.get("briefing", ""),
                handoff_file=str(handoff_path),
            )
        if self._type_name == "review":
            unit_test_paths = kwargs.get("unit_test_paths", [])
            if isinstance(unit_test_paths, str):
                unit_test_paths = [unit_test_paths]
            return _compose_review_context(
                plan_text=plan_text,
                subtask_name=kwargs.get("subtask_name", ""),
                worker_handoff_path=kwargs.get("worker_handoff_path", ""),
                unit_test_paths=unit_test_paths,
                review_file=str(handoff_path),
                briefing=kwargs.get("briefing", ""),
            )
        if self._type_name == "explore_files":
            return _compose_explore_context(
                task=kwargs.get("task", ""),
                handoff_file=str(handoff_path),
            )
        return kwargs.get("task", "")
