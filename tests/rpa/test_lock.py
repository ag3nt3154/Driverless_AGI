import json
import os
import subprocess
import sys
import time

import pytest

from rpa.lock import DesktopBusy, DesktopLock


def _spawn_dead_pid() -> int:
    """Spawn a short-lived subprocess, wait for it to exit, return its pid."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    return proc.pid


def test_acquire_and_holder(tmp_path):
    lock = DesktopLock(tmp_path / "desktop.lock")
    lock.acquire("agent-a")
    holder = lock.holder()
    assert holder is not None
    assert holder["agent"] == "agent-a"
    assert holder["pid"] == __import__("os").getpid()
    assert "since" in holder


def test_same_process_different_agents_excludes(tmp_path):
    lock = DesktopLock(tmp_path / "desktop.lock")
    lock.acquire("agent-a")
    with pytest.raises(DesktopBusy) as exc_info:
        lock.acquire("agent-b")
    assert "agent-a" in str(exc_info.value)


def test_reacquire_by_holder_is_noop(tmp_path):
    lock = DesktopLock(tmp_path / "desktop.lock")
    lock.acquire("agent-a")
    lock.acquire("agent-a")  # no-op, must not raise
    holder = lock.holder()
    assert holder["agent"] == "agent-a"


def test_dead_pid_lock_is_taken_over(tmp_path):
    dead_pid = _spawn_dead_pid()
    path = tmp_path / "desktop.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": dead_pid, "agent": "ghost", "since": "2020-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    lock = DesktopLock(path)
    lock.acquire("agent-a")
    holder = lock.holder()
    assert holder["agent"] == "agent-a"


def test_corrupt_lock_file_is_taken_over(tmp_path):
    path = tmp_path / "desktop.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json {{{", encoding="utf-8")
    old = time.time() - 60
    os.utime(path, (old, old))  # past the mid-write grace period
    lock = DesktopLock(path)
    lock.acquire("agent-a")
    holder = lock.holder()
    assert holder["agent"] == "agent-a"


def test_release_removes_file(tmp_path):
    path = tmp_path / "desktop.lock"
    lock = DesktopLock(path)
    lock.acquire("agent-a")
    assert path.exists()
    lock.release("agent-a")
    assert not path.exists()
    assert lock.holder() is None


def test_release_by_non_holder_is_noop(tmp_path):
    path = tmp_path / "desktop.lock"
    lock = DesktopLock(path)
    lock.acquire("agent-a")
    lock.release("agent-b")
    assert path.exists()
    holder = lock.holder()
    assert holder["agent"] == "agent-a"


def test_creates_parent_dirs_on_acquire(tmp_path):
    path = tmp_path / "nested" / "dir" / "desktop.lock"
    lock = DesktopLock(path)
    lock.acquire("agent-a")
    assert path.exists()


def test_default_path():
    from pathlib import Path

    lock = DesktopLock()
    assert lock.path == Path.home() / ".dagi" / "rpa" / "desktop.lock"


def test_fresh_unreadable_lock_is_not_taken_over(tmp_path):
    """A lock file still being written by its holder must not be deleted as corrupt."""
    path = tmp_path / "desktop.lock"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DesktopBusy):
        DesktopLock(path).acquire("B")
    assert path.exists()


def test_concurrent_takeover_of_a_dead_holder_has_one_winner(tmp_path, monkeypatch):
    import threading
    path = tmp_path / "desktop.lock"
    path.write_text(json.dumps({"pid": 999999999, "agent": "dead", "since": "x"}), encoding="utf-8")
    monkeypatch.setattr("rpa.lock.psutil.pid_exists", lambda pid: pid != 999999999)
    results: list = []
    barrier = threading.Barrier(8)

    def take(name):
        barrier.wait()
        try:
            DesktopLock(path).acquire(name)
            results.append(name)
        except DesktopBusy:
            pass

    threads = [threading.Thread(target=take, args=(f"a{i}",)) for i in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(results) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["agent"] == results[0]
