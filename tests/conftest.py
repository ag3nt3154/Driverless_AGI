"""tests/conftest.py — pytest plugin: RAM watchdog.

Monitors system RAM during every test. If usage exceeds
RAM_WARN_PCT (70%), the running test is interrupted with a clear
error. If usage exceeds RAM_KILL_PCT (90%), the process is
hard-killed to protect the machine.
"""
from __future__ import annotations

import ctypes
import os
import threading
import time

import psutil
import pytest

RAM_WARN_PCT = 70.0
RAM_KILL_PCT = 90.0
POLL_INTERVAL = 0.5


class _RAMExceeded(Exception):
    """Raised asynchronously in the test thread when RAM crosses the threshold."""


class _RamWatchdog:
    """Background daemon that polls system RAM and interrupts the test thread."""

    def __init__(self, test_thread_id: int, test_name: str) -> None:
        self._test_thread_id = test_thread_id
        self._test_name = test_name
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)

    def start(self) -> None:
        self._stop.clear()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _poll(self) -> None:
        while not self._stop.is_set():
            pct = psutil.virtual_memory().percent
            if pct >= RAM_KILL_PCT:
                msg = (
                    f"RAM at {pct:.1f}% (kill threshold {RAM_KILL_PCT}%) "
                    f"during {self._test_name} — hard-killing process"
                )
                print(f"\n!!! {msg}", flush=True)
                os._exit(1)
            if pct >= RAM_WARN_PCT:
                self._inject_exception()
                return
            self._stop.wait(POLL_INTERVAL)

    def _inject_exception(self) -> None:
        pct = psutil.virtual_memory().percent
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(self._test_thread_id),
            ctypes.py_object(_RAMExceeded),
        )
        self._stop.wait(1.0)
        new_pct = psutil.virtual_memory().percent
        if new_pct >= RAM_KILL_PCT:
            os._exit(1)


@pytest.fixture(autouse=True)
def _ram_watchdog(request: pytest.FixtureRequest) -> None:  # noqa: PT004
    """Auto-use fixture: starts a RAM watchdog for every test."""
    test_name = request.node.nodeid
    tid = threading.current_thread().ident
    watchdog = _RamWatchdog(test_thread_id=tid, test_name=test_name)
    watchdog.start()
    try:
        yield
    except _RAMExceeded:
        pct = psutil.virtual_memory().percent
        pytest.fail(
            f"RAM usage hit {pct:.0f}% (threshold {RAM_WARN_PCT}%) "
            f"during {test_name}. Likely infinite loop or memory leak.",
            pytrace=False,
        )
    finally:
        watchdog.stop()
