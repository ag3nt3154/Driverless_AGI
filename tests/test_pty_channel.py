"""Tests for agent/pty_channel.py — ConPTY wrapper."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.pty_channel import PtyChannel, PtyTimeoutError


def test_spawn_and_read_output(tmp_path):
    """Spawning a trivial process returns its stdout."""
    log = tmp_path / "out.log"
    ch = PtyChannel(
        argv=["python", "-c", "print('hello'); print('<<<DAGI_DONE>>>')"],
        log_file=log,
    )
    result = ch.read_until_sentinel(timeout=10)
    ch.terminate()
    assert "hello" in result
    assert log.read_text()  # log was written


def test_write_and_read(tmp_path):
    """Writing to stdin is reflected in stdout."""
    import time

    script = tmp_path / "echo_script.py"
    script.write_text(
        "import sys\n"
        "line = sys.stdin.readline().strip()\n"
        "print(f'echo:{line}')\n"
        "print('<<<DAGI_DONE>>>')\n"
    )
    log = tmp_path / "out.log"
    ch = PtyChannel(argv=["python", str(script)], log_file=log)
    time.sleep(0.5)  # let the process reach readline()
    ch.write("test_input\n")
    result = ch.read_until_sentinel(timeout=10)
    ch.terminate()
    assert "echo:test_input" in result


def test_timeout_raises(tmp_path):
    """read_until_sentinel raises PtyTimeoutError when sentinel never appears."""
    log = tmp_path / "out.log"
    ch = PtyChannel(
        argv=["python", "-c", "import time; time.sleep(60)"],
        log_file=log,
    )
    with pytest.raises(PtyTimeoutError):
        ch.read_until_sentinel(timeout=0.5)
    ch.terminate(force=True)


def test_ansi_stripped_from_result(tmp_path):
    """ANSI escape codes are stripped from the result text."""
    log = tmp_path / "out.log"
    ch = PtyChannel(
        argv=[
            "python", "-c",
            r"print('\x1b[32mcolored\x1b[0m text'); print('<<<DAGI_DONE>>>')",
        ],
        log_file=log,
    )
    result = ch.read_until_sentinel(timeout=10)
    ch.terminate()
    assert "\x1b" not in result
    assert "colored text" in result
