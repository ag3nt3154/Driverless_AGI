"""tests/test_session_log_revise.py — Tests for session log revision."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent import session_events as ev
from agent.session_log import SessionLog
from agent.session_store import write_session, read_session


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


class TestReviseLastStep:
    def test_raises_on_empty_log(self):
        log = SessionLog()
        with pytest.raises(ValueError, match="[Nn]o step"):
            log.revise_last_step()

    def test_removes_last_step_events(self):
        log = _build_log_with_steps(1, 2)
        initial_count = len(log.events)
        removed = log.revise_last_step()
        assert len(removed) > 0
        # Step 2 events should be gone; step 1 should remain
        remaining_types = [e.type for e in log.events]
        assert ev.STEP_END in remaining_types  # step 1's end
        # The removed events should include step_start, tool_call, tool_result, assistant_message, step_end
        removed_types = {e.type for e in removed}
        assert ev.STEP_START in removed_types
        assert ev.STEP_END in removed_types

    def test_surface_shrinks_after_removal(self):
        log = _build_log_with_steps(1, 2)
        msgs_before = len(log.derive_messages())
        log.revise_last_step()
        msgs_after = len(log.derive_messages())
        assert msgs_after < msgs_before

    def test_auto_removes_turn_when_last_step_removed(self):
        log = _build_log_with_steps(1, 1)
        log.revise_last_step()
        # The turn wrapper and user message should also be gone
        remaining_types = [e.type for e in log.events]
        assert ev.TURN_START not in remaining_types
        assert ev.USER_MESSAGE not in remaining_types
        assert ev.TURN_END not in remaining_types
        assert len(log.events) == 0

    def test_does_not_remove_turn_when_steps_remain(self):
        log = _build_log_with_steps(1, 2)
        log.revise_last_step()
        remaining_types = [e.type for e in log.events]
        assert ev.TURN_START in remaining_types
        assert ev.USER_MESSAGE in remaining_types

    def test_rewinds_internal_state(self):
        log = _build_log_with_steps(1, 2)
        log.revise_last_step()
        # open_turn should still be set (turn is still open with step 1)
        assert log.open_turn == 1
        assert log.open_step is None  # between steps

    def test_rewinds_state_after_full_turn_removal(self):
        log = _build_log_with_steps(2, 1)
        # Remove turn 2's only step — auto-removes the turn
        log.revise_last_step()
        assert log.open_turn is None  # turn 1 was already closed
        assert log.next_turn() == 2  # can reuse turn number 2

    def test_removes_tool_call_tracking(self):
        log = _build_log_with_steps(1, 2)
        # call_1_2 should be tracked
        assert "call_1_2" in log._calls
        log.revise_last_step()
        assert "call_1_2" not in log._calls

    def test_can_revise_down_to_empty(self):
        log = _build_log_with_steps(1, 1)
        log.revise_last_step()
        assert len(log.events) == 0
        assert log.derive_messages() == []
        assert log.open_turn is None
        assert log.open_step is None

    def test_seq_counter_stays_valid_for_future_appends(self):
        log = _build_log_with_steps(1, 2)
        log.revise_last_step()
        old_seq = log.seq
        # Should be able to append new events without seq collision
        log.append(ev.STEP_START, {"turn": 1, "step": 2})
        assert log.events[-1].seq > old_seq

    def test_on_append_not_called_during_revision(self):
        log = _build_log_with_steps(1, 1)
        calls = []
        log.on_append = lambda e: calls.append(e)
        log.revise_last_step()
        assert len(calls) == 0


class TestReviseWithPersistence:
    def test_rewrite_after_revise_produces_loadable_log(self, tmp_path: Path):
        log = _build_log_with_steps(2, 2)
        path = tmp_path / "test.events.jsonl"
        write_session(path, log.events)

        # Revise one step
        log.revise_last_step()
        write_session(path, log.events)

        # Reload and verify
        reloaded = read_session(path)
        assert len(reloaded) == len(log.events)
        for orig, loaded in zip(log.events, reloaded):
            assert orig.seq == loaded.seq
            assert orig.type == loaded.type

    def test_reloaded_log_has_correct_derived_state(self, tmp_path: Path):
        log = _build_log_with_steps(1, 2)
        log.revise_last_step()
        path = tmp_path / "test.events.jsonl"
        write_session(path, log.events)

        reloaded_events = read_session(path)
        new_log = SessionLog(seed=reloaded_events)
        assert new_log.open_turn == log.open_turn
        assert new_log.open_step == log.open_step
        assert len(new_log.derive_messages()) == len(log.derive_messages())

    def test_revise_all_then_rewrite_produces_empty_log(self, tmp_path: Path):
        log = _build_log_with_steps(1, 1)
        log.revise_last_step()
        path = tmp_path / "test.events.jsonl"
        write_session(path, log.events)

        reloaded = read_session(path)
        assert len(reloaded) == 0
