"""tests/test_session_log.py — Session event vocabulary and append-only log."""
from __future__ import annotations

import pytest

from agent import session_events as ev
from agent.session_log import InvariantError, SessionEvent, SessionLog


class TestVocabulary:
    def test_surface_types_are_exactly_the_message_producing_four(self):
        """A closed set: anything outside it structurally cannot cost tokens."""
        assert ev.SURFACE_EVENT_TYPES == frozenset(
            {"user/message", "assistant/message", "tool/result", "context/compaction"}
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


def _open_turn(log: SessionLog, turn: int = 1) -> None:
    log.append(ev.TURN_START, {"turn": turn})


class TestTurnEnclosure:
    def test_surface_event_outside_a_turn_is_rejected(self):
        log = SessionLog()
        with pytest.raises(InvariantError, match="outside an open turn"):
            log.append(
                ev.USER_MESSAGE,
                {"turn": 1, "step": 1, "role": "user", "content": "hi", "source": "human"},
                surface_op="append",
            )

    def test_surface_event_inside_a_turn_is_accepted(self):
        log = SessionLog()
        _open_turn(log)
        e = log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 1, "role": "user", "content": "hi", "source": "human"},
            surface_op="append",
        )
        assert e.seq == 2

    def test_log_only_events_are_legal_between_turns(self):
        """Recommendation §5.6: strict for surface, permissive for log-only.

        Skill-reload and plan-mode rebuilds fire from idle TUI slash commands;
        forcing wrapper turns around them buys nothing, because a log-only
        event is folded latest-wins and has nothing to lose.
        """
        log = SessionLog()
        log.append(ev.REQUEST_HEADER, {"header": {"system": "s"}, "reason": "initial"})
        log.append(ev.PLAN_WRITE, {"plan": []})
        assert log.seq == 2

    def test_open_turn_reports_the_live_turn(self):
        log = SessionLog()
        assert log.open_turn is None
        _open_turn(log, 4)
        assert log.open_turn == 4
        log.append(ev.TURN_END, {"turn": 4, "reason": ev.reason_completed()})
        assert log.open_turn is None

    def test_nested_turn_start_is_rejected(self):
        log = SessionLog()
        _open_turn(log, 1)
        with pytest.raises(InvariantError, match="already open"):
            log.append(ev.TURN_START, {"turn": 2})

    def test_turn_end_without_open_turn_is_rejected(self):
        log = SessionLog()
        with pytest.raises(InvariantError, match="no open turn"):
            log.append(ev.TURN_END, {"turn": 1, "reason": ev.reason_completed()})


class TestTurnNumberDerivation:
    def test_next_turn_is_derived_from_the_log_not_a_counter(self):
        seed = [
            SessionEvent(seq=1, time="t", type=ev.TURN_START, data={"turn": 7}),
            SessionEvent(
                seq=2, time="t", type=ev.TURN_END,
                data={"turn": 7, "reason": {"kind": "completed"}},
            ),
        ]
        log = SessionLog(seed=seed)
        assert log.next_turn() == 8

    def test_next_turn_is_one_for_a_fresh_log(self):
        assert SessionLog().next_turn() == 1


class TestSurfaceOpPresence:
    def test_surface_event_without_surface_op_is_rejected(self):
        log = SessionLog()
        _open_turn(log)
        with pytest.raises(InvariantError, match="requires surface_op"):
            log.append(
                ev.USER_MESSAGE,
                {"turn": 1, "step": 1, "role": "user", "content": "hi", "source": "human"},
            )

    def test_log_only_event_with_surface_op_is_rejected(self):
        log = SessionLog()
        with pytest.raises(InvariantError, match="must not carry surface_op"):
            log.append(ev.PLAN_WRITE, {"plan": []}, surface_op="append")


class TestToolPairing:
    def test_tool_result_must_share_the_step_of_its_call(self):
        log = SessionLog()
        _open_turn(log)
        log.append(ev.STEP_START, {"turn": 1, "step": 1})
        log.append(
            ev.TOOL_CALL,
            {"turn": 1, "step": 1, "call_id": "c1", "name": "read", "arguments": "{}"},
        )
        with pytest.raises(InvariantError, match="step mismatch"):
            log.append(
                ev.TOOL_RESULT,
                {"turn": 1, "step": 2, "call_id": "c1", "content": "x", "meta": None},
                surface_op="append",
            )

    def test_tool_result_without_a_call_is_rejected(self):
        log = SessionLog()
        _open_turn(log)
        log.append(ev.STEP_START, {"turn": 1, "step": 1})
        with pytest.raises(InvariantError, match="no matching tool/call"):
            log.append(
                ev.TOOL_RESULT,
                {"turn": 1, "step": 1, "call_id": "ghost", "content": "x", "meta": None},
                surface_op="append",
            )


class TestSurfaceIntegration:
    def _log_with_two_surface_nodes(self) -> SessionLog:
        log = SessionLog()
        _open_turn(log)
        log.append(ev.STEP_START, {"turn": 1, "step": 1})
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 1, "role": "user", "content": "a", "source": "human"},
            surface_op="append",
        )
        log.append(
            ev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "b"}},
            surface_op="append",
        )
        return log

    def test_derive_messages_reflects_the_surface(self):
        log = self._log_with_two_surface_nodes()
        assert [m["content"] for m in log.derive_messages()] == ["a", "b"]

    def test_boundary_events_contribute_no_messages(self):
        log = self._log_with_two_surface_nodes()
        log.append(ev.STEP_END, {"turn": 1, "step": 1})
        log.append(ev.PLAN_WRITE, {"plan": [{"content": "x", "status": "pending"}]})
        assert len(log.derive_messages()) == 2

    def test_replace_over_a_dead_node_is_rejected(self):
        log = self._log_with_two_surface_nodes()
        with pytest.raises(InvariantError, match="not a live surface node"):
            log.append(
                ev.USER_MESSAGE,
                {"turn": 1, "step": 1, "role": "user", "content": "s", "source": "compact"},
                surface_op=("replace", 99, 99),
                source_seqs=[99],
            )

    def test_replace_must_cite_every_shadowed_node(self):
        log = self._log_with_two_surface_nodes()
        with pytest.raises(InvariantError, match="must cite every shadowed node"):
            log.append(
                ev.USER_MESSAGE,
                {"turn": 1, "step": 1, "role": "user", "content": "s", "source": "compact"},
                surface_op=("replace", 3, 4),
                source_seqs=[3],  # omits node 4
            )

    def test_a_well_formed_replace_is_accepted(self):
        log = self._log_with_two_surface_nodes()
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 1, "role": "user", "content": "s", "source": "compact"},
            surface_op=("replace", 3, 4),
            source_seqs=[3, 4],
        )
        assert [m["content"] for m in log.derive_messages()] == ["s"]

    def test_the_raw_log_survives_a_replace(self):
        """Append-only means shadowed events are hidden, never deleted."""
        log = self._log_with_two_surface_nodes()
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 1, "role": "user", "content": "s", "source": "compact"},
            surface_op=("replace", 3, 4),
            source_seqs=[3, 4],
        )
        assert [e.seq for e in log.events] == [1, 2, 3, 4, 5]


class TestLatestHeader:
    def test_returns_none_for_a_log_without_a_header(self):
        assert SessionLog().latest_header() is None

    def test_returns_the_most_recent_header(self):
        log = SessionLog()
        log.append(ev.REQUEST_HEADER, {"system": "old", "reason": "initial"})
        log.append(ev.REQUEST_HEADER, {"system": "new", "reason": "change"})
        assert log.latest_header()["system"] == "new"

    def test_header_is_log_only_and_never_reaches_the_surface(self):
        log = SessionLog()
        log.append(ev.REQUEST_HEADER, {"system": "s", "reason": "initial"})
        assert log.derive_messages() == []
