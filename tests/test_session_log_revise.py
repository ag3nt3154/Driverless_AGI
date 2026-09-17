"""tests/test_session_log_revise.py — Tests for session log revision."""
from __future__ import annotations

import pytest

from agent import session_events as ev
from agent.session_log import SessionLog


def _build_log_with_steps(n_turns: int, steps_per_turn: int) -> SessionLog:
    """Build a SessionLog with the given number of turns, each with the given steps.

    Each step contains a tool/call, tool/result, and assistant/message.
    """
    log = SessionLog()
    for t in range(1, n_turns + 1):
        log.append(ev.TURN_START, {"turn": t})
        log.append(ev.USER_MESSAGE, {"turn": t, "step": 0, "role": "user", "content": f"User turn {t}"}, surface_op="append")
        for s in range(1, steps_per_turn + 1):
            call_id = f"call_{t}_{s}"
            log.append(ev.STEP_START, {"turn": t, "step": s})
            log.append(ev.TOOL_CALL, {"turn": t, "step": s, "call_id": call_id, "name": f"tool_{s}", "input": {}})
            log.append(ev.TOOL_RESULT, {"turn": t, "step": s, "call_id": call_id, "content": f"result {s}"}, surface_op="append")
            log.append(ev.ASSISTANT_MESSAGE, {"turn": t, "step": s, "message": {"role": "assistant", "content": f"Response t{t}s{s}"}}, surface_op="append")
            log.append(ev.STEP_END, {"turn": t, "step": s})
        log.append(ev.TURN_END, {"turn": t, "reason": ev.reason_completed()})
    return log


class TestPeekLastStep:
    def test_returns_none_on_empty_log(self):
        log = SessionLog()
        assert log.peek_last_step() is None

    def test_returns_summary_for_single_step(self):
        log = _build_log_with_steps(1, 1)
        info = log.peek_last_step()
        assert info is not None
        assert info.step_number == 1  # absolute step count
        assert info.turn == 1
        assert info.tool_names == ["tool_1"]
        assert "Response t1s1" in info.assistant_snippet

    def test_returns_last_step_of_multi_step_turn(self):
        log = _build_log_with_steps(1, 3)
        info = log.peek_last_step()
        assert info is not None
        assert info.step_number == 3
        assert info.turn == 1
        assert info.tool_names == ["tool_3"]

    def test_returns_last_step_across_turns(self):
        log = _build_log_with_steps(2, 2)
        info = log.peek_last_step()
        assert info is not None
        assert info.step_number == 4  # 2 steps per turn * 2 turns = 4 total
        assert info.turn == 2

    def test_returns_none_when_only_boundary_events(self):
        log = SessionLog()
        log.append(ev.TURN_START, {"turn": 1})
        log.append(ev.USER_MESSAGE, {"turn": 1, "step": 0, "role": "user", "content": "hi"}, surface_op="append")
        # No steps — just a turn with a user message
        info = log.peek_last_step()
        assert info is None
