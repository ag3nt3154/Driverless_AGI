"""tests/test_subagent_owner.py — R20: subagent cancellation is scoped to the owning loop.

Interrupting one AgentLoop must kill only the subagents that loop spawned; children of
other concurrent loops (GUI agents share one process) and of no loop must survive.
kill_process_tree is mocked: these tests prove target selection, not real tree termination.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from tools import _subagent_runner as runner
from tests.test_streaming_loop import _make_loop, _stream_client, _wh_chunks
from tests.test_subagent_runner import _make_state


@pytest.fixture
def killed(monkeypatch):
    """Record every proc passed to kill_process_tree instead of killing it."""
    procs: list = []
    monkeypatch.setattr("tools._subagent_runner.kill_process_tree", procs.append)
    return procs


@pytest.fixture(autouse=True)
def _clean_active():
    yield
    with runner._active_lock:
        runner._active.clear()


def _register(tmp_path, pid: int, owner: str | None):
    """Put an in-flight child with this owner into the runner's active table."""
    sub = tmp_path / f"child_{pid}_{owner}"
    sub.mkdir()
    state, proc = _make_state(sub, poll_side_effect=lambda: None)
    proc.pid = pid
    state.owner = owner
    with runner._active_lock:
        runner._active[pid] = state
    return state, proc


def _spawn_timed_out(tmp_path, monkeypatch) -> int:
    """Run the real run_subagent with a fake process that times out; returns its PID."""
    proc = MagicMock()
    proc.pid = 7001
    proc.stdout = iter([])
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(runner, "_poll_until", lambda state, timeout: {"status": "timeout", "pid": state.proc.pid})
    result = runner.run_subagent("worker", "task", tmp_path, tmp_path / "h" / "worker_x.md", timeout=0.1)
    assert result == {"status": "timeout", "pid": 7001}
    return 7001


# ── owner scope ──────────────────────────────────────────────────────────────

def test_owner_scope_sets_and_restores_the_current_owner():
    assert runner.current_owner() is None
    with runner.owner_scope("A"):
        assert runner.current_owner() == "A"
        with runner.owner_scope("B"):
            assert runner.current_owner() == "B"
        assert runner.current_owner() == "A"
    assert runner.current_owner() is None


def test_owner_scope_does_not_leak_into_other_threads():
    seen: list = []
    with runner.owner_scope("A"):
        t = threading.Thread(target=lambda: seen.append(runner.current_owner()))
        t.start()
        t.join()
    assert seen == [None]


def test_run_subagent_records_the_scope_owner_and_keeps_it_after_timeout(tmp_path, monkeypatch):
    with runner.owner_scope("A"):
        pid = _spawn_timed_out(tmp_path, monkeypatch)
    with runner._active_lock:
        assert runner._active[pid].owner == "A"


def test_run_subagent_outside_any_scope_records_no_owner(tmp_path, monkeypatch):
    pid = _spawn_timed_out(tmp_path, monkeypatch)
    with runner._active_lock:
        assert runner._active[pid].owner is None


# ── owner-filtered kill ──────────────────────────────────────────────────────

def test_kill_with_owner_kills_only_that_owners_children(tmp_path, killed):
    _, proc_a = _register(tmp_path, 101, "A")
    state_b, proc_b = _register(tmp_path, 102, "B")
    state_none, proc_none = _register(tmp_path, 103, None)

    assert runner.force_kill_active_subagents(owner="A") == 1

    assert killed == [proc_a]
    with runner._active_lock:
        assert runner._active == {102: state_b, 103: state_none}
    assert state_b.task_file.exists() and state_none.task_file.exists()


def test_kill_with_owner_kills_its_timed_out_child(tmp_path, monkeypatch, killed):
    with runner.owner_scope("A"):
        pid = _spawn_timed_out(tmp_path, monkeypatch)
    _, proc_b = _register(tmp_path, 102, "B")

    runner.force_kill_active_subagents(owner="A")

    assert [p.pid for p in killed] == [pid]
    with runner._active_lock:
        assert set(runner._active) == {102}


def test_reused_pid_belongs_to_the_new_owner(tmp_path, killed):
    state_a, _ = _register(tmp_path, 555, "A")
    runner._cleanup_terminal_state(state_a)          # A's child exits ...
    state_b, proc_b = _register(tmp_path, 555, "B")  # ... and B's new child gets the same PID

    assert runner.force_kill_active_subagents(owner="A") == 0

    assert killed == []
    with runner._active_lock:
        assert runner._active == {555: state_b}


def test_kill_without_owner_still_kills_every_owner(tmp_path, killed):
    procs = [_register(tmp_path, pid, owner)[1] for pid, owner in ((1, "A"), (2, "B"), (3, None))]

    assert runner.force_kill_active_subagents() == 3

    assert sorted(p.pid for p in killed) == [1, 2, 3]
    with runner._active_lock:
        assert runner._active == {}


# ── AgentLoop ownership ──────────────────────────────────────────────────────

def test_each_loop_has_a_distinct_stable_owner_id():
    a, b = _make_loop(), _make_loop()
    assert a._owner_id and b._owner_id and a._owner_id != b._owner_id
    assert a._owner_id == a._owner_id


def test_interrupting_one_loop_spares_the_other_loops_subagents(tmp_path, killed):
    loop_a, loop_b = _make_loop(), _make_loop()
    _, proc_a = _register(tmp_path, 201, loop_a._owner_id)
    state_b, _ = _register(tmp_path, 202, loop_b._owner_id)

    assert loop_a.interrupt() is True

    assert killed == [proc_a]
    with runner._active_lock:
        assert runner._active == {202: state_b}
    assert not loop_b.is_paused


def test_run_dispatches_tools_inside_the_loops_owner_scope():
    loop = _make_loop(stream=True)
    seen: list = []
    original = loop.registry.dispatch.side_effect

    def dispatch(name, args):
        seen.append(runner.current_owner())
        return original(name, args)

    loop.registry.dispatch.side_effect = dispatch
    loop.client, _ = _stream_client(_wh_chunks("ok"))

    loop.run("do it")

    assert seen == [loop._owner_id]
    assert runner.current_owner() is None


@pytest.mark.parametrize(
    ("target", "call"),
    [
        ("agent._compaction.compact", lambda loop: loop.compact(force=True)),
        ("agent.wtf.run_wtf", lambda loop: loop.run_wtf("why")),
    ],
)
def test_compact_and_wtf_run_inside_the_loops_owner_scope(target, call):
    loop = _make_loop()
    seen: list = []
    with patch(target, side_effect=lambda *a, **k: seen.append(runner.current_owner())):
        call(loop)
    assert seen == [loop._owner_id]
