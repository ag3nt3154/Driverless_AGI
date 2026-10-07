import os
import platform
import re
import subprocess
import sys
import threading
from pathlib import Path

from agent.base_tool import BaseTool
from agent._process_kill import kill_process_tree

# cmd.exe quotes only with "; an apostrophe there is literal and must not hide a pipe.
_QUOTED = re.compile(r"\"[^\"]*\"" if sys.platform == "win32" else r"\"[^\"]*\"|'[^']*'")
# A lone |: not part of ||, and not escaped as \| (sh) or ^| (cmd).
_PIPE = re.compile(r"(?<![|^\\])\|(?!\|)")
PIPE_STATUS_NOTE = "[note: piped command, exit status is from the last command only]"


def _has_pipe(command: str) -> bool:
    """True when *command* pipes output, ignoring quoted text, || and escaped pipes."""
    return bool(_PIPE.search(_QUOTED.sub("", command)))


def _process_group_kwargs() -> dict:
    """Start the shell in its own process group so a kill takes the whole tree."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _format_result(output: str, returncode: int, command: str) -> str:
    """Append the exit-code marker and, for pipes, which command that status belongs to."""
    if returncode != 0:
        output += f"\n[exit code {returncode}]"
    if _has_pipe(command):
        output += f"\n{PIPE_STATUS_NOTE}"
    return output or "[no output]"


def _describe_platform() -> str:
    """Name the OS and the shell Popen(shell=True) really launches.

    Windows runs %COMSPEC% (cmd.exe), POSIX always runs /bin/sh — never bash as such.
    """
    if sys.platform != "win32":
        release = platform.release()
        return f"Platform: {sys.platform} ({release}); shell: /bin/sh (POSIX sh syntax)."
    version = platform.version()
    build = version.rsplit(".", 1)[-1]
    if build.isdigit() and int(build) >= 22000:
        name = "Windows 11"  # still reports major version 10
    else:
        name = "Windows 10" if version.startswith("10.") else "Windows"
    shell = os.environ.get("COMSPEC", "cmd.exe")
    return (
        f"Platform: {name} ({version}); shell: {shell}; cmd syntax, not bash "
        "(dir, type, where, %VAR%, backslash paths)."
    )


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Execute a shell command within the project directory. "
        "Returns stdout and stderr. Optionally provide a timeout in seconds "
        "(defaults to 120s if omitted). Long output is already cut to its first and last "
        "lines, so do not pipe it through more/findstr/head/tail to shorten it: with a pipe "
        "the exit code is only the last command's, which can hide a failure."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (optional)"},
        },
        "required": ["command"],
    }

    DEFAULT_TIMEOUT = 120.0
    _REAP_GRACE = 5.0  # seconds to wait for a killed tree to release its output pipes

    def __init__(self, cwd: Path = Path("."), default_timeout: float = DEFAULT_TIMEOUT):
        self.cwd = cwd
        self.description = f"{type(self).description} {_describe_platform()}"
        self.default_timeout = default_timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._killed_by_user = False

    def run(self, command: str, timeout: int | None = None) -> str:
        r = self.run_structured(command, timeout)
        if r["timed_out"]:
            return r["output"]
        if r["killed"]:
            return f"{r['output']}\n[killed by user]" if r["output"] else "[killed by user]"
        return _format_result(r["output"], r["exit_code"], command)

    def run_structured(self, command: str, timeout: int | None = None) -> dict:
        """Run *command*; return {output, exit_code, timed_out, killed} without formatting.

        On a timeout, output is the "[timed out …]" message and exit_code is None.
        Used directly by the `code` tool, where a non-zero exit is data, not an error.
        """
        effective_timeout = timeout if timeout is not None else self.default_timeout

        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.cwd),
            **_process_group_kwargs(),
        )
        with self._lock:
            self._proc = proc
            self._killed_by_user = False
        try:
            try:
                stdout, stderr = proc.communicate(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                kill_process_tree(proc)
                # A shelled-out command tree (e.g. npm -> node) can leave grandchild
                # processes holding the stdout/stderr pipes open even after the
                # immediate shell is killed, so this drain is itself bounded.
                try:
                    proc.communicate(timeout=self._REAP_GRACE)
                except subprocess.TimeoutExpired:
                    pass
                message = (
                    f"[timed out after {effective_timeout}s and was terminated — "
                    "pass a longer explicit timeout for long-running commands]"
                )
                return {"output": message, "exit_code": None, "timed_out": True, "killed": False}
        finally:
            with self._lock:
                self._proc = None

        output = (stdout or "") + (stderr or "")
        return {
            "output": output,
            "exit_code": proc.returncode,
            "timed_out": False,
            "killed": self._killed_by_user,
        }

    def force_kill(self) -> bool:
        """Force-kill the currently running command, if any. Returns whether
        anything was actually killed."""
        with self._lock:
            proc = self._proc
            if proc is None:
                return False
            self._killed_by_user = True
        kill_process_tree(proc)
        return True
