from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from agent.prompts import load_prompt

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker

_PLAN_SUBAGENT_SYSTEM_PROMPT = load_prompt("plan_subagent.md")


def build_plan_agent_config(
    base_config: "AgentConfig",
    plan_file: Path,
    project_path: Path,
    plan_mode_initiated_by: str = "user",
) -> "AgentConfig":
    """Build an AgentConfig for a plan agent (used by both PlanSubAgent and the CLI plan loop)."""
    from dataclasses import replace
    plan_cfg = base_config.plan_config or base_config
    return replace(
        base_config,
        model=plan_cfg.model,
        base_url=plan_cfg.base_url,
        api_key=plan_cfg.api_key,
        thinking=plan_cfg.thinking,
        context_window=plan_cfg.context_window,
        reserve_tokens=plan_cfg.reserve_tokens,
        keep_recent_tokens=plan_cfg.keep_recent_tokens,
        system_prompt=_PLAN_SUBAGENT_SYSTEM_PROMPT,
        plan_mode=True,
        plan_file=str(plan_file),
        plan_mode_initiated_by=plan_mode_initiated_by,
        project_path=project_path,
        worker_config=None,
        plan_config=None,
    )


class PlanSubAgent:
    """Runs an isolated plan-writing sub-agent.

    Uses plan_config model if set, falls back to the parent config model.
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
        from agent.sub_agent import SubAgentConfig, SubAgentRunner
        from tools.find import FindTool
        from tools.grep import GrepTool
        from tools.read import ReadTool
        from tools.show_plan import ShowPlanTool
        from tools.web_research import WebResearchTool
        from tools.write import WriteTool

        config = self._config
        project_path = config.project_path
        dagi_root = Path(__file__).parent.parent
        effective_roots = [dagi_root, project_path]

        subagent_cfg = build_plan_agent_config(
            config, self._plan_file, project_path, plan_mode_initiated_by="dagi"
        )

        sub_tools = [
            ReadTool(cwd=project_path, allowed_roots=effective_roots),
            GrepTool(cwd=project_path, allowed_roots=effective_roots),
            FindTool(cwd=project_path, allowed_roots=effective_roots),
            # WriteTool scoped to only the plan file via single-file allowed_root
            WriteTool(cwd=project_path, allowed_roots=[self._plan_file]),
            WebResearchTool(config=subagent_cfg, callbacks=self._callbacks, cwd=project_path, tracker=self._tracker),
            ShowPlanTool(plan_file=self._plan_file, callbacks=self._callbacks),
        ]

        subagent_id = uuid4().hex[:8]
        depth = (self._tracker._depth if self._tracker else 0)

        if self._tracker:
            self._tracker.record_subagent_start(subagent_id, "plan_subagent", task, depth)

        runner = SubAgentRunner(
            config=subagent_cfg,
            tools=sub_tools,
            system_prompt=_PLAN_SUBAGENT_SYSTEM_PROMPT,
            callbacks=self._callbacks,
            sub_cfg=SubAgentConfig(prefix="[plan]"),
            parent_tracker=self._tracker,
            subagent_id=subagent_id,
        )
        result = runner.run(task)

        if self._tracker:
            self._tracker.record_subagent_end(subagent_id, result, depth)

        return result
