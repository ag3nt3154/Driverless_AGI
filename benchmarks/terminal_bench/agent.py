from __future__ import annotations

import os
from pathlib import Path

from terminal_bench.agents.base_agent import AgentResult, BaseAgent
from terminal_bench.agents.failure_mode import FailureMode
from terminal_bench.terminal.tmux_session import TmuxSession

from agent.config_loader import resolve_model_config
from agent.loop import AgentLoop, AgentCallbacks
from tools.tmux_bash import TmuxBashTool


class DagiAgent(BaseAgent):
    """Terminal-bench 2 agent backed by DAGI's AgentLoop.

    Configuration via environment variables:
        DAGI_BENCH_MODEL  — model key from config_benchmark.yaml
                            (default: claude-sonnet-openrouter)
    """

    @staticmethod
    def name() -> str:
        return "dagi"

    def perform_task(
        self,
        instruction: str,
        session: TmuxSession,
        logging_dir: Path | None = None,
    ) -> AgentResult:
        model_key = os.environ.get("DAGI_BENCH_MODEL", "claude-sonnet-openrouter")
        bench_config = Path(__file__).parent.parent.parent / "config_benchmark.yaml"
        config = resolve_model_config(model_key, config_path=bench_config)
        config.project_path = logging_dir or Path(".")

        bash_tool = TmuxBashTool(session)
        loop = AgentLoop(config, callbacks=AgentCallbacks(), _bash_tool=bash_tool)
        try:
            loop.run(instruction)
        except Exception:
            loop.finish()
            return AgentResult(failure_mode=FailureMode.FATAL_LLM_PARSE_ERROR)
        loop.finish()

        assistant_nodes = [m for m in loop.tracker._messages if m.entity == "assistant"]
        total_in = sum(m.input_tokens for m in assistant_nodes if m.input_tokens)
        total_out = sum(m.output_tokens for m in assistant_nodes if m.output_tokens)

        return AgentResult(
            total_input_tokens=total_in,
            total_output_tokens=total_out,
        )
