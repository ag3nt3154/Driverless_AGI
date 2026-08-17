"""tests/test_context_spec.py — Context reconstruction from session log + spec."""
from __future__ import annotations

import pytest

from agent import session_events as ev
from agent.session_log import SessionLog
from agent.context_spec import BranchSegment, ContextSpec, reconstruct


def _populated_log() -> SessionLog:
    """Build a log with main turn 1 (2 steps) and a branch forked at (1, 1)."""
    log = SessionLog()
    # -- main: header + turn 1 --
    log.append(ev.REQUEST_HEADER, {"system": "sys", "reason": "initial"})
    log.append(ev.TURN_START, {"turn": 1})
    # step 0: user message
    log.append(
        ev.USER_MESSAGE,
        {"turn": 1, "step": 0, "role": "user", "content": "task", "source": "human"},
        surface_op="append",
    )
    # step 1: assistant + tool
    log.append(ev.STEP_START, {"turn": 1, "step": 1})
    log.append(
        ev.ASSISTANT_MESSAGE,
        {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "calling tool"}},
        surface_op="append",
    )
    log.append(
        ev.TOOL_CALL,
        {"turn": 1, "step": 1, "call_id": "c1", "name": "run_worker", "arguments": "{}"},
    )
    # fork here
    log.append(
        ev.BRANCH_START,
        {"branch": "sub_1", "parent_branch": "main", "turn": 1, "step": 1},
    )
    # -- branch: sub_1 turn 1 --
    log.append(ev.TURN_START, {"turn": 1}, branch="sub_1")
    log.append(
        ev.USER_MESSAGE,
        {"turn": 1, "step": 0, "role": "user", "content": "sub instructions", "source": "human"},
        surface_op="append",
        branch="sub_1",
    )
    log.append(ev.STEP_START, {"turn": 1, "step": 1}, branch="sub_1")
    log.append(
        ev.ASSISTANT_MESSAGE,
        {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "sub result"}},
        surface_op="append",
        branch="sub_1",
    )
    log.append(ev.STEP_END, {"turn": 1, "step": 1}, branch="sub_1")
    log.append(ev.TURN_END, {"turn": 1, "reason": ev.reason_completed()}, branch="sub_1")
    # -- back on main: tool result at step 1 --
    log.append(
        ev.TOOL_RESULT,
        {"turn": 1, "step": 1, "call_id": "c1", "content": "handoff text", "meta": None},
        surface_op="append",
    )
    log.append(ev.STEP_END, {"turn": 1, "step": 1})
    log.append(ev.TURN_END, {"turn": 1, "reason": ev.reason_completed()})
    return log


class TestContextSpecReconstruct:
    def test_main_only_context(self):
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
        ])
        header, messages = reconstruct(log, spec)
        assert header == {"role": "system", "content": "sys"}
        contents = [m.get("content") for m in messages]
        assert "task" in contents
        assert "calling tool" in contents
        assert "handoff text" in contents
        assert "sub instructions" not in contents
        assert "sub result" not in contents

    def test_subagent_context_shares_parent_prefix(self):
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
            BranchSegment(branch="sub_1", turns=[(1, [0, 1])]),
        ])
        header, messages = reconstruct(log, spec)
        assert header == {"role": "system", "content": "sys"}
        contents = [m.get("content") for m in messages]
        # Parent prefix present
        assert "task" in contents
        assert "calling tool" in contents
        # Branch content present
        assert "sub instructions" in contents
        assert "sub result" in contents
        # Handoff (main step 1 tool_result) NOT present — it came after the fork
        assert "handoff text" not in contents

    def test_parent_prefix_precedes_branch_content(self):
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
            BranchSegment(branch="sub_1", turns=[(1, [0, 1])]),
        ])
        _, messages = reconstruct(log, spec)
        contents = [m.get("content") for m in messages if m.get("content")]
        task_idx = contents.index("task")
        sub_idx = contents.index("sub instructions")
        assert task_idx < sub_idx

    def test_empty_spec_returns_header_only(self):
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[]),
        ])
        header, messages = reconstruct(log, spec)
        assert header == {"role": "system", "content": "sys"}
        assert messages == []

    def test_branch_segment_without_main_first_raises(self):
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="sub_1", turns=[(1, [0])]),
        ])
        with pytest.raises(ValueError, match="must start with"):
            reconstruct(log, spec)
