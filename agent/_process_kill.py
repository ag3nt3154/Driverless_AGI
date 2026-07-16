"""agent/_process_kill.py — Shared process-tree kill helper.

Used by tools/bash.py (timeout kills and user-triggered force_kill()) and
tools/_subagent_runner.py (Esc-triggered subagent kill) so there is one
place that knows how to forcibly kill a full process tree on both platforms.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys


def kill_process_tree(proc: subprocess.Popen) -> None:
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
