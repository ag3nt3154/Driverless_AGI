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
from tools._task_envelope import wrap_envelope

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


def _compose_worker_body(plan_text: str, subtask_name: str) -> str:
    """Build the worker's task body: just the `## Subtask` section, if any.

    Envelope sections (Instructions/Output) are added later by `wrap_envelope`.
    """
    from tools._plan_parser import extract_subtask

    subtask_ctx = extract_subtask(plan_text, subtask_name, include_tests=False) if plan_text else ""
    return f"## Subtask\n{subtask_ctx}" if subtask_ctx else ""


def _compose_review_body(
    plan_text: str,
    subtask_name: str,
    worker_handoff_path: str,
    unit_test_paths: list[str],
) -> str:
    """Build the review's task body: `## Subtask Being Reviewed` and
    `## Worker Handoff` (which folds in the unit test paths, real content the
    reviewer needs, not path-delivery prose). Envelope sections are added
    later by `wrap_envelope`.
    """
    from tools._plan_parser import extract_subtask

    subtask_ctx = extract_subtask(plan_text, subtask_name, include_tests=True) if plan_text else ""

    sections: list[str] = []
    if subtask_ctx:
        sections.append(f"## Subtask Being Reviewed\n{subtask_ctx}")
    if worker_handoff_path:
        lines = [
            f"The worker's implementation report is at: {worker_handoff_path}",
            "Read it before evaluating the subtask.",
        ]
        unit_test_list = "\n".join(unit_test_paths) if unit_test_paths else ""
        if unit_test_list:
            lines.append(f"Unit test paths:\n{unit_test_list}")
        sections.append("## Worker Handoff\n" + "\n".join(lines))

    return "\n\n---\n\n".join(sections)


def _compose_generic_body(task: str) -> str:
    """Build the task body for types with no dedicated composer (explore_files,
    web_research, memory-query, memory-add, document-reader)."""
    return f"## Task\n{task}" if task else ""


def _normalize_unit_test_paths(unit_test_paths) -> list[str]:
    if isinstance(unit_test_paths, str):
        return [unit_test_paths]
    return unit_test_paths or []


def _worker_body_builder(plan_text: str, kwargs: dict) -> str:
    return _compose_worker_body(plan_text, kwargs.get("subtask_name", ""))


def _review_body_builder(plan_text: str, kwargs: dict) -> str:
    return _compose_review_body(
        plan_text=plan_text,
        subtask_name=kwargs.get("subtask_name", ""),
        worker_handoff_path=kwargs.get("worker_handoff_path", ""),
        unit_test_paths=_normalize_unit_test_paths(kwargs.get("unit_test_paths", [])),
    )


_BODY_BUILDERS: dict = {
    "worker": _worker_body_builder,
    "review": _review_body_builder,
}


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
        self._default_handoff_spec = self._load_default_handoff_spec(type_name, config)

    @staticmethod
    def _load_type_data(type_name: str, config: "AgentConfig") -> dict:
        """Return the full parsed subagent_config.yaml for a type.

        Tries the project-local override first, then the `_DAGI_ROOT`-relative
        default. Returns the first candidate that defines a `parameters`
        block (matching the original `_load_parameters` search semantics), or
        `{}` if neither is usable.
        """
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
                    return data
            except (FileNotFoundError, OSError, yaml.YAMLError):
                pass
        return {}

    @staticmethod
    def _load_parameters(type_name: str, config: "AgentConfig") -> dict:
        data = SpawnSubagentTool._load_type_data(type_name, config)
        return data.get("parameters", _FALLBACK_PARAMETERS)

    @staticmethod
    def _load_default_handoff_spec(type_name: str, config: "AgentConfig") -> str:
        data = SpawnSubagentTool._load_type_data(type_name, config)
        return data.get("default_handoff_spec", "")

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

        return self._dispatch_result(result)

    def _dispatch_result(self, result: dict) -> str:
        """Translate a `run_subagent` result dict into the tool's return string."""
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
        """Build the full task text: a type-specific body plus the universal
        `## Instructions` / `## Output` envelope. `handoff_path` is no longer
        embedded in the body — the subagent process learns its handoff path
        via `--handoff`, independent of the task text (see `_subagent_runner`).
        """
        del handoff_path  # kept for call-site/test compatibility; unused in body
        plan_text = _load_plan_text(self._config)
        builder = _BODY_BUILDERS.get(self._type_name)
        if builder:
            body = builder(plan_text, kwargs)
        else:
            body = _compose_generic_body(kwargs.get("task", ""))

        handoff_spec = kwargs.get("handoff_spec", "") or self._default_handoff_spec
        return wrap_envelope(body, kwargs.get("briefing", ""), handoff_spec)
