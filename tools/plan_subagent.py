from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker


def build_plan_agent_config(
    base_config: "AgentConfig",
    plan_file: Path,
    project_path: Path,
    plan_mode_initiated_by: str = "user",
) -> "AgentConfig":
    """Build an AgentConfig for a plan agent (used by both PlanSubAgent and the CLI plan loop)."""
    from dataclasses import replace
    advanced_cfg = base_config.advanced_config or base_config
    return replace(
        base_config,
        model=advanced_cfg.model,
        base_url=advanced_cfg.base_url,
        api_key=advanced_cfg.api_key,
        thinking=advanced_cfg.thinking,
        context_window=advanced_cfg.context_window,
        reserve_tokens=advanced_cfg.reserve_tokens,
        keep_recent_tokens=advanced_cfg.keep_recent_tokens,
        system_prompt=_PLAN_SUBAGENT_SYSTEM_PROMPT,
        plan_mode=True,
        plan_file=str(plan_file),
        plan_mode_initiated_by=plan_mode_initiated_by,
        project_path=project_path,
        worker_config=None,
        advanced_config=None,
    )


class PlanSubAgent:
    """Runs an isolated plan-writing sub-agent.

    Uses advanced_config model if set, falls back to the parent config model.
    Tools are restricted to read/grep/find + write to the plan file only.
    """

    def __init__(
        self,
        config: AgentConfig,
        plan_file: Path,
        callbacks: AgentCallbacks | None = None,
        tracker: SessionTracker | None = None,
    ) -> None:
        self._config = config
        self._plan_file = plan_file
        self._callbacks = callbacks
        self._tracker = tracker

    def run(self, task: str) -> str:
        from tools._terminal_subagent import spawn_terminal_subagent

        config = self._config
        project_path = config.project_path

        subagent_id = uuid4().hex[:8]
        depth = (self._tracker._depth if self._tracker else 0)

        if self._tracker:
            self._tracker.record_subagent_start(subagent_id, "plan_subagent", task, depth)

        result = spawn_terminal_subagent(
            subagent_type="plan",
            task=task,
            project_path=project_path,
            plan_file=self._plan_file,
            timeout=600,   # planning is slower than typical tasks
        )

        if self._tracker:
            self._tracker.record_subagent_end(subagent_id, result, depth)

        return result
