import os
import signal
import subprocess
import sys
from pathlib import Path

from agent.base_tool import BaseTool


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Execute a bash command within the project directory. "
        "Returns stdout and stderr. Optionally provide a timeout in seconds "
        "(defaults to 120s if omitted)."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (optional)"},
        },
        "required": ["command"],
    }

    DEFAULT_TIMEOUT = 120.0
    _REAP_GRACE = 5.0  # seconds to wait for a killed tree to release its output pipes

    def __init__(self, cwd: Path = Path("."), default_timeout: float = DEFAULT_TIMEOUT):
        self.cwd = cwd
        self.default_timeout = default_timeout

    def run(self, command: str, timeout: int | None = None) -> str:
        effective_timeout = timeout if timeout is not None else self.default_timeout

        popen_kwargs: dict = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.cwd),
            **popen_kwargs,
        )
        try:
            stdout, stderr = proc.communicate(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            self._kill_tree(proc)
            # A shelled-out command tree (e.g. npm -> node) can leave grandchild
            # processes holding the stdout/stderr pipes open even after the
            # immediate shell is killed, so this drain is itself bounded.
            try:
                proc.communicate(timeout=self._REAP_GRACE)
            except subprocess.TimeoutExpired:
                pass
            return (
                f"[timed out after {effective_timeout}s and was terminated — "
                "pass a longer explicit timeout for long-running commands]"
            )

        output = (stdout or "") + (stderr or "")
        if proc.returncode != 0:
            output += f"\n[exit code {proc.returncode}]"
        return output or "[no output]"

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        """Kill the whole process tree, not just the shell's direct child."""
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            proc.kill()
        except ProcessLookupError:
            pass
