"""tests/test_session_log.py — Session event vocabulary and append-only log."""
from __future__ import annotations

import pytest

from agent import session_events as ev
from agent.session_log import InvariantError, SessionEvent, SessionLog


class TestVocabulary:
    def test_surface_types_are_exactly_three(self):
        assert ev.SURFACE_EVENT_TYPES == frozenset(
            {"user/message", "assistant/message", "tool/result"}
        )

    def test_surface_types_are_a_subset_of_known_types(self):
        assert ev.SURFACE_EVENT_TYPES <= ev.KNOWN_EVENT_TYPES

    def test_boundary_types_are_known_but_not_surface(self):
        for t in (ev.TURN_START, ev.TURN_END, ev.STEP_START, ev.STEP_END):
            assert t in ev.KNOWN_EVENT_TYPES
            assert t not in ev.SURFACE_EVENT_TYPES

    def test_log_only_types_are_known_but_not_surface(self):
        for t in (ev.TOOL_CALL, ev.REQUEST_HEADER, ev.PLAN_WRITE, ev.END_SEED):
            assert t in ev.KNOWN_EVENT_TYPES
            assert t not in ev.SURFACE_EVENT_TYPES

    def test_format_version_is_one(self):
        assert ev.SESSION_FORMAT_VERSION == 1


class TestTurnEndReasons:
    def test_completed(self):
        assert ev.reason_completed() == {"kind": "completed"}

    def test_max_continuations(self):
        assert ev.reason_max_continuations() == {"kind": "max-continuations"}

    def test_aborted_carries_typed_cause(self):
        assert ev.reason_aborted("user") == {"kind": "aborted", "cause": {"kind": "user"}}

    def test_error_defaults_to_unknown_code(self):
        assert ev.reason_error("boom") == {
            "kind": "error",
            "error": {"message": "boom", "code": "UNKNOWN"},
        }

    def test_interrupted_is_reserved_for_crash_repair(self):
        assert ev.reason_interrupted() == {"kind": "interrupted"}


class TestSessionEvent:
    def test_round_trips_through_json(self):
        e = SessionEvent(
            seq=3,
            time="2026-08-16T00:00:00+00:00",
            type=ev.USER_MESSAGE,
            data={"turn": 1, "step": 1, "role": "user", "content": "hi", "source": "human"},
            surface_op="append",
        )
        assert SessionEvent.from_json(e.to_json()) == e

    def test_omits_absent_optional_fields_from_json(self):
        e = SessionEvent(seq=1, time="t", type=ev.TURN_START, data={"turn": 1})
        raw = e.to_json()
        assert "surface_op" not in raw
        assert "source_seqs" not in raw
        assert "ignorable" not in raw

    def test_is_immutable(self):
        e = SessionEvent(seq=1, time="t", type=ev.TURN_START, data={"turn": 1})
        with pytest.raises(Exception):
            e.seq = 2


class TestSessionLogAppend:
    def test_seq_starts_at_one_and_is_contiguous(self):
        log = SessionLog()
        assert log.seq == 0
        a = log.append(ev.TURN_START, {"turn": 1})
        b = log.append(ev.STEP_START, {"turn": 1, "step": 1})
        assert (a.seq, b.seq) == (1, 2)
        assert log.seq == 2

    def test_rejects_unknown_event_type(self):
        log = SessionLog()
        with pytest.raises(InvariantError, match="unknown event type"):
            log.append("bogus/event", {})

    def test_rejects_non_json_serialisable_data(self):
        log = SessionLog()
        log.append(ev.TURN_START, {"turn": 1})
        with pytest.raises(InvariantError, match="not JSON-serialisable"):
            log.append(ev.PLAN_WRITE, {"plan": object()})

    def test_data_is_snapshotted_so_later_mutation_cannot_leak_in(self):
        log = SessionLog()
        payload = {"turn": 1}
        e = log.append(ev.TURN_START, payload)
        payload["turn"] = 99
        assert e.data["turn"] == 1

    def test_seed_continues_the_sequence(self):
        seed = [SessionEvent(seq=1, time="t", type=ev.TURN_START, data={"turn": 1})]
        log = SessionLog(seed=seed)
        assert log.seq == 1
        assert log.append(ev.TURN_END, {"turn": 1, "reason": ev.reason_completed()}).seq == 2
