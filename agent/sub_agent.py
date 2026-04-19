from dataclasses import dataclass, replace

from agent.base_tool import BaseTool
from agent.loop import AgentCallbacks, AgentConfig
from agent.registry import ToolRegistry


@dataclass
class SubAgentConfig:
    max_iterations: int = 8
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
    ) -> None:
        sub_cfg = sub_cfg or SubAgentConfig()
        self._system_prompt = system_prompt

        # Inherit model/auth/context from parent; cap iterations and disable plan mode
        self._config = replace(
            config,
            max_iterations=min(config.max_iterations, sub_cfg.max_iterations),
            plan_mode=False,
            plan_file=None,
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
        )
        return loop.run(task)
