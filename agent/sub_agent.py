from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from agent.base_tool import BaseTool
from agent.loop import AgentCallbacks, AgentConfig
from agent.registry import ToolRegistry

if TYPE_CHECKING:
    from agent.session import SessionTracker


@dataclass
class SubAgentConfig:
    prefix: str = "[sub-agent]"


class SubAgentRunner:
    """Runs an isolated sub-agent with a focused tool set and system prompt.

    The sub-agent inherits the parent's model/auth config but gets its own
    registry and system prompt. Token updates are forwarded to the parent's
    callbacks so costs accumulate in the parent's running totals.
    """

    def __init__(
        self,
        config: AgentConfig,
        tools: list[BaseTool],
        system_prompt: str,
        callbacks: AgentCallbacks | None = None,
        sub_cfg: SubAgentConfig | None = None,
        parent_tracker: "SessionTracker | None" = None,
        subagent_id: str | None = None,
    ) -> None:
        sub_cfg = sub_cfg or SubAgentConfig()
        self._system_prompt = system_prompt
        self._parent_tracker = parent_tracker
        self._subagent_id = subagent_id

        # Use worker model if configured; fall back to parent model.
        # Only LLM-specific fields (model, base_url, api_key, thinking, token limits)
        # come from the worker — project context always stays from the parent.
        w = config.worker_config or config
        self._config = replace(
            config,
            model=w.model,
            base_url=w.base_url,
            api_key=w.api_key,
            thinking=w.thinking,
            context_window=w.context_window,
            reserve_tokens=w.reserve_tokens,
            keep_recent_tokens=w.keep_recent_tokens,
            plan_mode=False,
            plan_file=None,
            worker_config=None,  # prevent further nesting
        )

        self._registry = ToolRegistry()
        for tool in tools:
            self._registry.register(tool)

        # Forward tool callbacks with prefix so the UI shows sub-agent activity.
        # on_token_update is forwarded so sub-agent tokens roll up into the
        # parent's running totals (both count and cost).
        # on_done / on_error are NOT forwarded — they would fire the parent
        # UI's session-complete footer in the middle of the parent task.
        if callbacks:
            pfx = sub_cfg.prefix
            self._callbacks = AgentCallbacks(
                on_tool_start=lambda n, d, a, _p=pfx: callbacks.on_tool_start(f"{_p} {n}", d, a),
                on_tool_end=lambda n, r, _p=pfx: callbacks.on_tool_end(f"{_p} {n}", r),
                on_assistant_text=callbacks.on_assistant_text,
                on_token_update=callbacks.on_token_update,
                on_iteration=callbacks.on_iteration,
                on_compaction=callbacks.on_compaction,
                on_reasoning=callbacks.on_reasoning,
            )
        else:
            self._callbacks = None

    def run(self, task: str) -> str:
        from agent.loop import AgentLoop  # lazy to avoid circular import at module load
        initial_messages = [{"role": "system", "content": self._system_prompt}]
        loop = AgentLoop(
            config=self._config,
            callbacks=self._callbacks,
            initial_messages=initial_messages,
            _registry=self._registry,
            _parent_tracker=self._parent_tracker,
            _subagent_id=self._subagent_id,
        )
        result = loop.run(task)
        loop.finish()  # rolls child stats up to root; no file write
        return result
