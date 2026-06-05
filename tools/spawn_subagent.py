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

_DAGI_ROOT = Path(__file__).parent.parent

_FALLBACK_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "The task or query to send to the subagent.",
        },
    },
    "required": ["task"],
}


def _load_agents_md(dagi_root: Path, project_path: Path) -> str:
    parts: list[str] = []
    for base in (dagi_root, project_path):
        agents_file = base / ".dagi" / "agents.md"
        try:
            text = agents_file.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
        except (FileNotFoundError, OSError):
            pass
    return "\n\n".join(parts)


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
    agents_md: str,
    plan_text: str,
    subtask_name: str,
    custom_instructions: str,
    handoff_file: str,
) -> str:
    from tools._plan_parser import extract_global_sections, extract_subtask

    global_ctx = extract_global_sections(plan_text) if plan_text else ""
    subtask_ctx = extract_subtask(plan_text, subtask_name, include_tests=False) if plan_text else ""

    sections: list[str] = []
    if agents_md:
        sections.append(f"## Project Description\n{agents_md}")
    if global_ctx:
        sections.append(f"## Plan Context\n{global_ctx}")
    if subtask_ctx:
        sections.append(f"## Your Subtask\n{subtask_ctx}")
    if custom_instructions:
        sections.append(f"## Custom Instructions\n{custom_instructions}")
    sections.append(f"## Output\nWrite your handoff report to: {handoff_file}")

    return "\n\n---\n\n".join(sections)


def _compose_review_context(
    agents_md: str,
    plan_text: str,
    subtask_name: str,
    handoff_report_path: str,
    unit_test_paths: list[str],
    review_file: str,
    custom_instructions: str,
) -> str:
    from tools._plan_parser import extract_global_sections, extract_subtask

    global_ctx = extract_global_sections(plan_text) if plan_text else ""
    subtask_ctx = extract_subtask(plan_text, subtask_name, include_tests=True) if plan_text else ""

    sections: list[str] = []
    if agents_md:
        sections.append(f"## Project Description\n{agents_md}")
    if global_ctx:
        sections.append(f"## Plan Context\n{global_ctx}")
    if subtask_ctx:
        sections.append(f"## Subtask Being Reviewed\n{subtask_ctx}")
    if custom_instructions:
        sections.append(f"## Custom Instructions\n{custom_instructions}")

    unit_test_list = "\n".join(unit_test_paths) if unit_test_paths else ""
    output_lines = [f"Handoff report path: {handoff_report_path}"]
    if unit_test_list:
        output_lines.append(f"Unit test paths:\n{unit_test_list}")
    output_lines.append(f"Write your review report to: {review_file}")
    sections.append("## Output Files\n" + "\n".join(output_lines))

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
        timeout: float = 300.0,
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
        search_paths = [
            config.project_path / ".dagi" / "subagents" / type_name / "subagent_config.yaml",
            _DAGI_ROOT / ".dagi" / "subagents" / type_name / "subagent_config.yaml",
        ]
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

        if result["status"] == "ok":
            return f"Subagent completed. Handoff written to: {result['handoff']}"
        if result["status"] == "timeout":
            return json.dumps({"status": "timeout", "pid": result["pid"]})
        return f"[{self._type_name} error] {result.get('message', 'unknown error')}"

    def _compose_task(self, handoff_path: Path, **kwargs) -> str:
        agents_md = _load_agents_md(_DAGI_ROOT, self._config.project_path)
        plan_text = _load_plan_text(self._config)

        if self._type_name == "worker":
            return _compose_worker_context(
                agents_md=agents_md,
                plan_text=plan_text,
                subtask_name=kwargs.get("subtask_name", ""),
                custom_instructions=kwargs.get("custom_instructions", ""),
                handoff_file=str(handoff_path),
            )
        if self._type_name == "review":
            unit_test_paths = kwargs.get("unit_test_paths", [])
            if isinstance(unit_test_paths, str):
                unit_test_paths = [unit_test_paths]
            return _compose_review_context(
                agents_md=agents_md,
                plan_text=plan_text,
                subtask_name=kwargs.get("subtask_name", ""),
                handoff_report_path=kwargs.get("handoff_report_path", ""),
                unit_test_paths=unit_test_paths,
                review_file=str(handoff_path),
                custom_instructions=kwargs.get("custom_instructions", ""),
            )
        return kwargs.get("task", "")
