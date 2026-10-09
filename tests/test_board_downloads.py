from __future__ import annotations

import threading
import time
import subprocess
import sys

from pyside_gui.board_downloads import DownloadPool


def test_pool_runs_at_most_two_jobs_and_returns_results():
    gate = threading.Event()
    entered = 0
    peak = 0
    lock = threading.Lock()

    def work(value, cancel):
        nonlocal entered, peak
        with lock:
            entered += 1
            peak = max(peak, entered)
        gate.wait(2)
        with lock:
            entered -= 1
        return value

    pool = DownloadPool(work)
    futures = [pool.submit(index) for index in range(4)]
    deadline = time.monotonic() + 2
    while peak < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert peak == 2
    gate.set()
    assert [future.result(timeout=2) for future in futures] == list(range(4))
    pool.stop()


def test_stop_cancels_queued_and_signals_active_without_joining():
    entered = threading.Event()
    release = threading.Event()

    def work(value, cancel):
        entered.set()
        while not cancel.is_set() and not release.is_set():
            time.sleep(0.01)
        return value

    pool = DownloadPool(work, workers=1)
    active = pool.submit(1)
    queued = pool.submit(2)
    assert entered.wait(1)
    started = time.monotonic()
    pool.stop()
    assert time.monotonic() - started < 0.2
    assert queued.cancelled()
    release.set()
    assert active.result(timeout=1) == 1


def test_submit_after_stop_is_cancelled():
    pool = DownloadPool(lambda value, cancel: value)
    pool.stop()
    assert pool.submit(1).cancelled()


def test_stalled_daemon_worker_does_not_delay_process_exit():
    code = """
import threading
from pyside_gui.board_downloads import DownloadPool
entered = threading.Event()
def work(value, cancel):
    entered.set()
    threading.Event().wait(60)
pool = DownloadPool(work, workers=1)
pool.submit(1)
assert entered.wait(2)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
