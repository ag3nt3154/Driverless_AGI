"""tests/test_ipc.py — Unit tests for the file-based IPC channel (agent/ipc.py)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from agent.ipc import IpcChannel, IpcTimeoutError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ch(tmp_path: Path) -> IpcChannel:
    return IpcChannel(tmp_path / "ipc")


# ── write_task / poll_task ────────────────────────────────────────────────────

def test_write_task_creates_file(tmp_path: Path) -> None:
    ch = _ch(tmp_path)
    ch.write_task(1, "hello world")
    f = ch.ipc_dir / "task_1.json"
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data == {"seq": 1, "task": "hello world"}


def test_poll_task_returns_dict(tmp_path: Path) -> None:
    ch = _ch(tmp_path)
    ch.write_task(3, "do something")
    result = ch.poll_task(3, timeout=1.0)
    assert result is not None
    assert result["seq"] == 3
    assert result["task"] == "do something"


def test_poll_task_returns_none_on_exit(tmp_path: Path) -> None:
    ch = _ch(tmp_path)
    ch.write_exit()
    result = ch.poll_task(1, timeout=1.0)
    assert result is None


def test_poll_task_timeout_raises(tmp_path: Path) -> None:
    ch = _ch(tmp_path)
    with pytest.raises(IpcTimeoutError):
        ch.poll_task(99, timeout=0.3)


def test_poll_task_written_late(tmp_path: Path) -> None:
    """Task written after polling starts is still picked up."""
    ch = _ch(tmp_path)

    def _write_late() -> None:
        time.sleep(0.3)
        ch.write_task(1, "late task")

    threading.Thread(target=_write_late, daemon=True).start()
    result = ch.poll_task(1, timeout=2.0)
    assert result is not None
    assert result["task"] == "late task"


# ── write_result / poll_result ────────────────────────────────────────────────

def test_write_result_creates_file(tmp_path: Path) -> None:
    ch = _ch(tmp_path)
    ch.write_result(2, status="ok", result="done", error="")
    f = ch.ipc_dir / "result_2.json"
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data == {"seq": 2, "status": "ok", "result": "done", "error": ""}


def test_poll_result_returns_dict(tmp_path: Path) -> None:
    ch = _ch(tmp_path)
    ch.write_result(5, status="ok", result="output text")
    data = ch.poll_result(5, timeout=1.0)
    assert data["status"] == "ok"
    assert data["result"] == "output text"


def test_poll_result_timeout_raises(tmp_path: Path) -> None:
    ch = _ch(tmp_path)
    with pytest.raises(IpcTimeoutError):
        ch.poll_result(77, timeout=0.3)


def test_poll_result_written_late(tmp_path: Path) -> None:
    ch = _ch(tmp_path)

    def _write_late() -> None:
        time.sleep(0.3)
        ch.write_result(1, status="ok", result="async result")

    threading.Thread(target=_write_late, daemon=True).start()
    data = ch.poll_result(1, timeout=2.0)
    assert data["result"] == "async result"


# ── poll_ready ────────────────────────────────────────────────────────────────

def test_poll_ready_immediate(tmp_path: Path) -> None:
    ch = _ch(tmp_path)
    ch.write_ready()
    assert ch.poll_ready(timeout=1.0) is True


def test_poll_ready_timeout_raises(tmp_path: Path) -> None:
    ch = _ch(tmp_path)
    with pytest.raises(IpcTimeoutError):
        ch.poll_ready(timeout=0.3)


def test_poll_ready_written_late(tmp_path: Path) -> None:
    ch = _ch(tmp_path)

    def _write_late() -> None:
        time.sleep(0.3)
        ch.write_ready()

    threading.Thread(target=_write_late, daemon=True).start()
    assert ch.poll_ready(timeout=2.0) is True


# ── write_exit ────────────────────────────────────────────────────────────────

def test_write_exit_creates_sentinel(tmp_path: Path) -> None:
    ch = _ch(tmp_path)
    ch.write_exit()
    assert (ch.ipc_dir / "exit").exists()


# ── Sequence integrity ────────────────────────────────────────────────────────

def test_multiple_tasks_in_sequence(tmp_path: Path) -> None:
    """Multiple task/result cycles work without interference."""
    ch = _ch(tmp_path)
    for seq in range(1, 4):
        ch.write_task(seq, f"task {seq}")
    for seq in range(1, 4):
        t = ch.poll_task(seq, timeout=1.0)
        assert t is not None
        assert t["task"] == f"task {seq}"
        ch.write_result(seq, status="ok", result=f"result {seq}")
    for seq in range(1, 4):
        r = ch.poll_result(seq, timeout=1.0)
        assert r["result"] == f"result {seq}"
