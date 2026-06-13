from __future__ import annotations

from pathlib import Path

from agent.base_tool import BaseTool
from terminal_bench.terminal.tmux_session import TmuxSession


class TmuxBashTool(BaseTool):
    """BashTool replacement that executes commands inside a Terminal-bench TmuxSession."""

    name = "tmux_bash"
    description = (
        "Execute a bash command inside the benchmark container terminal via tmux. "
        "Returns the terminal output after the command completes. "
        "Optionally provide a timeout in seconds (default: 30)."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (optional, default 30)"},
        },
        "required": ["command"],
    }

    def __init__(self, session: TmuxSession) -> None:
        self._session = session

    def run(self, command: str, timeout: int | None = None) -> str:
        max_timeout = float(timeout or 30)
        try:
            self._session.send_keys(
                keys=[command, "Enter"],
                block=True,
                max_timeout_sec=max_timeout,
            )
        except TimeoutError:
            output = self._session.capture_pane()
            return f"[command timed out after {max_timeout:.0f}s]\n{output}"
        output = self._session.capture_pane(capture_entire=False)
        return output or "[no output]"
