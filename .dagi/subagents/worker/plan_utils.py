# .dagi/subagents/worker/plan_utils.py
"""Plan loading and task body composition for the worker subagent."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.loop import AgentConfig


def load_plan_text(config: "AgentConfig") -> str:
    """Read plan text from config.active_plan_file or config.plan_file."""
    for attr in ("active_plan_file", "plan_file"):
        plan_path = getattr(config, attr, None)
        if plan_path is not None:
            try:
                return Path(plan_path).read_text(encoding="utf-8")
            except (FileNotFoundError, OSError):
                pass
    return ""


def compose_worker_task(plan_text: str, subtask_name: str) -> str:
    """Build the worker task body: global plan context + subtask section.

    Envelope sections (Instructions/Output) are added later by run_subagent.
    """
    from tools._plan_parser import extract_global_sections, extract_subtask

    sections: list[str] = []

    if plan_text:
        global_ctx = extract_global_sections(plan_text)
        if global_ctx:
            sections.append(f"## Plan Context\n{global_ctx}")

        subtask_ctx = extract_subtask(plan_text, subtask_name, include_tests=False)
        if subtask_ctx:
            sections.append(f"## Subtask\n{subtask_ctx}")

    return "\n\n---\n\n".join(sections)
