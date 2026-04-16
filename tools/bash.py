import subprocess
from pathlib import Path

from agent.base_tool import BaseTool


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Execute a bash command within the project directory. "
        "Returns stdout and stderr. Optionally provide a timeout in seconds."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (optional)"},
        },
        "required": ["command"],
    }

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, command: str, timeout: int | None = None) -> str:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=timeout,
            text=True,
            cwd=str(self.cwd),
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            output += f"\n[exit code {result.returncode}]"
        return output or "[no output]"
