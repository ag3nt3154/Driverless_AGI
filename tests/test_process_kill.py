"""tests/test_process_kill.py — Unit test for agent/_process_kill.py."""
from __future__ import annotations

import subprocess
import sys
import time

from agent._process_kill import kill_process_tree


def test_kill_process_tree_terminates_a_running_process():
    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        **popen_kwargs,
    )
    time.sleep(0.5)  # let it actually start

    kill_process_tree(proc)

    proc.wait(timeout=5)
    assert proc.returncode is not None
