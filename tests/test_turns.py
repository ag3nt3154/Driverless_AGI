"""tests/test_turns.py — TurnBoundaries, the one writer of turn/step brackets."""
from __future__ import annotations

import pytest

from agent import session_events as sev
from agent._turns import TurnBoundaries
from agent.session_log import SessionLog


def _types(log: SessionLog) -> list[str]:
    return [e.type for e in log.events]


def test_steps_number_from_one_per_turn() -> None:
    log = SessionLog()
    turns = TurnBoundaries(log)
    assert turns.open_turn() == 1
    assert [turns.start_step(), turns.end_step(), turns.start_step()] == [1, None, 2]
    turns.close_turn(sev.reason_completed())
    turns.open_turn()
    assert turns.start_step() == 1


def test_close_turn_closes_the_open_step_and_is_idempotent() -> None:
    log = SessionLog()
    turns = TurnBoundaries(log)
    turns.open_turn()
    turns.start_step()
    turns.close_turn(sev.reason_completed())
    turns.close_turn(sev.reason_completed())
    turns.end_step()
    assert _types(log) == [sev.TURN_START, sev.STEP_START, sev.STEP_END, sev.TURN_END]
    assert turns.turn is None


def test_resync_step_continues_after_remaining_steps() -> None:
    log = SessionLog()
    turns = TurnBoundaries(log)
    turns.open_turn()
    for _ in range(3):
        turns.start_step()
        turns.end_step()
    log.revise_last_step(keep_turn=True)
    log.revise_last_step(keep_turn=True)
    turns.resync_step()
    assert turns.start_step() == 2


def test_revise_with_keep_turn_keeps_the_turn_and_user_message() -> None:
    log = SessionLog()
    turns = TurnBoundaries(log)
    turns.open_turn()
    log.append(sev.USER_MESSAGE, {"turn": 1, "step": 0, "role": "user",
                                  "content": "task", "source": "human"}, surface_op="append")
    turns.start_step()
    turns.end_step()
    log.revise_last_step(keep_turn=True)
    assert log.open_turn == 1
    assert log.derive_messages() == [{"role": "user", "content": "task"}]


def test_side_turn_closes_as_completed() -> None:
    log = SessionLog()
    with TurnBoundaries(log).side_turn(source="gui_compact") as turn:
        assert turn == 1
    end = log.events[-1]
    assert end.type == sev.TURN_END and end.data["reason"]["kind"] == "completed"
    assert log.events[0].data == {"turn": 1, "source": "gui_compact"}


def test_side_turn_closes_as_error_when_the_body_raises() -> None:
    log = SessionLog()
    with pytest.raises(ValueError):
        with TurnBoundaries(log).side_turn():
            raise ValueError("boom")
    assert log.open_turn is None
    assert log.events[-1].data["reason"] == sev.reason_error("boom", "ValueError")
