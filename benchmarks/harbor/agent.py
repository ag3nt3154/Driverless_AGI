from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from agent.config_loader import resolve_model_config
from agent.loop import AgentCallbacks, AgentLoop
from benchmarks.harbor.bash_tool import HarborBashTool


class DagiAgent(BaseAgent):
    """Harbor benchmark agent backed by DAGI's AgentLoop.

    Configuration via environment variables:
        DAGI_BENCH_MODEL  — model key from config_benchmark.yaml
                            (default: whatever default_model is set in config_benchmark.yaml)

    Architecture:
        harbor run
          └─ DagiAgent.run(instruction, environment, context)
               └─ AgentLoop in thread pool  (avoids blocking event loop)
                    └─ HarborBashTool.run(command)
                         └─ run_coroutine_threadsafe → environment.exec(command)
    """

    @staticmethod
    def name() -> str:
        return "dagi"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        """No container setup required — DAGI drives everything via bash commands."""

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        event_loop = asyncio.get_event_loop()

        def exec_command(command: str, timeout: int | None = None) -> str:
            """Sync bridge: submits environment.exec() to the event loop from a thread."""
            timeout_sec = float(timeout or 60)
            future = asyncio.run_coroutine_threadsafe(
                environment.exec(command, timeout_sec=timeout_sec),
                event_loop,
            )
            try:
                result = future.result(timeout=timeout_sec + 5)
            except TimeoutError:
                return f"[command timed out after {timeout_sec:.0f}s]"
            output = (result.stdout or "") + (result.stderr or "")
            return output.strip() or "[no output]"

        # None → resolve_model_config reads default_model from config_benchmark.yaml
        model_key = os.environ.get("DAGI_BENCH_MODEL") or None
        bench_config = Path(__file__).parent.parent.parent / "config_benchmark.yaml"
        config = resolve_model_config(model_key, config_path=bench_config)
        config.project_path = Path(tempfile.mkdtemp())

        bash_tool = HarborBashTool(exec_fn=exec_command)
        loop = AgentLoop(config, callbacks=AgentCallbacks(), _bash_tool=bash_tool)

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, loop.run, instruction
            )
        finally:
            loop.finish()

        self._populate_context(loop, context)

    @staticmethod
    def _populate_context(loop: AgentLoop, context: AgentContext) -> None:
        """Fill AgentContext with token statistics from the completed run."""
        assistant_nodes = [m for m in loop.tracker._messages if m.entity == "assistant"]
        context.n_input_tokens = sum(
            m.input_tokens for m in assistant_nodes if m.input_tokens
        )
        context.n_output_tokens = sum(
            m.output_tokens for m in assistant_nodes if m.output_tokens
        )
