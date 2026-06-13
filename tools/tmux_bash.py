"""tools/tmux_bash.py — TmuxBashTool: first-class tmux-based bash tool.

Executes commands inside a Terminal-bench TmuxSession. This module is the
canonical location; benchmarks/terminal_bench/tmux_bash_tool.py is kept for
backwards compatibility.
"""
from __future__ import annotations

from agent.base_tool import BaseTool


class TmuxBashTool(BaseTool):
    """BashTool replacement that executes commands inside a Terminal-bench TmuxSession."""

    name = "tmux_bash"
    description = (
        "Execute a bash command in the benchmark container terminal via tmux. "
        "Returns the terminal output after the command completes. "
        "Optionally provide a timeout in seconds (default: 30)."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to execute"},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (optional, default 30)",
            },
        },
        "required": ["command"],
    }

    def __init__(self, session: object) -> None:
        self._session = session

    def run(self, command: str, timeout: int | None = None) -> str:
        max_timeout = float(timeout or 30)
        try:
            self._session.send_keys(  # type: ignore[union-attr]
                keys=[command, "Enter"],
                block=True,
                max_timeout_sec=max_timeout,
            )
        except TimeoutError:
            output = self._session.capture_pane()  # type: ignore[union-attr]
            return f"[command timed out after {max_timeout:.0f}s]\n{output}"
        output = self._session.capture_pane(capture_entire=False)  # type: ignore[union-attr]
        return output or "[no output]"
