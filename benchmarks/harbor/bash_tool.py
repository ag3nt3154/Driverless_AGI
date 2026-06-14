from __future__ import annotations

from typing import Callable

from agent.base_tool import BaseTool


class HarborBashTool(BaseTool):
    """BashTool replacement that executes commands via Harbor's BaseEnvironment.

    The ``exec_fn`` is a sync wrapper created by ``DagiAgent.run()`` that
    bridges the async ``environment.exec()`` back to the sync AgentLoop thread
    using ``asyncio.run_coroutine_threadsafe``.
    """

    name = "harbor_bash"
    description = (
        "Execute a bash command in the Harbor benchmark container. "
        "Returns stdout/stderr after the command completes. "
        "Optionally provide a timeout in seconds (default: 60)."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Bash command to execute in the container",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (optional, default 60)",
            },
        },
        "required": ["command"],
    }

    def __init__(self, exec_fn: Callable[[str, int | None], str]) -> None:
        """
        Args:
            exec_fn: Sync callable ``(command, timeout) -> output`` that routes
                     execution through ``environment.exec()`` via the event-loop
                     bridge in ``DagiAgent.run()``.
        """
        self._exec_fn = exec_fn

    def run(self, command: str, timeout: int | None = None) -> str:
        return self._exec_fn(command, timeout)
