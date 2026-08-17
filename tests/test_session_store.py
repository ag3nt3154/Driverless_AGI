"""tests/test_session_store.py — Durability for the session event log."""
from __future__ import annotations

import json

import pytest

from agent import session_events as ev
from agent.session_log import SessionLog
from agent.session_store import (
    IncompatibleFormat,
    append_event,
    read_session,
    write_session,
)


def _log() -> SessionLog:
    log = SessionLog()
    log.append(ev.REQUEST_HEADER, {"system": "sys", "reason": "initial"})
    log.append(ev.TURN_START, {"turn": 1})
    log.append(
        ev.USER_MESSAGE,
        {"turn": 1, "step": 0, "role": "user", "content": "hello", "source": "human"},
        surface_op="append",
    )
    return log


class TestRoundTrip:
    def test_write_then_read_preserves_every_event(self, tmp_path):
        path = tmp_path / "s.jsonl"
        write_session(path, _log().events)
        assert [e.seq for e in read_session(path)] == [1, 2, 3]

    def test_round_trip_preserves_surface_ops(self, tmp_path):
        path = tmp_path / "s.jsonl"
        write_session(path, _log().events)
        assert read_session(path)[2].surface_op == "append"

    def test_reloaded_events_reseed_an_equivalent_log(self, tmp_path):
        path = tmp_path / "s.jsonl"
        original = _log()
        write_session(path, original.events)
        restored = SessionLog(seed=read_session(path))
        assert restored.derive_messages() == original.derive_messages()
        assert restored.seq == original.seq

    def test_the_first_line_is_a_version_header(self, tmp_path):
        path = tmp_path / "s.jsonl"
        write_session(path, _log().events)
        first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert first == {"format": ev.SESSION_FORMAT_VERSION, "kind": "dagi-session-log"}


class TestAppend:
    def test_append_creates_the_file_with_a_header(self, tmp_path):
        path = tmp_path / "s.jsonl"
        for event in _log().events:
            append_event(path, event)
        lines = path.read_text(encoding="utf-8").splitlines()
        # 1 header + 3 events
        assert len(lines) == 4
        assert [e.seq for e in read_session(path)] == [1, 2, 3]

    def test_append_is_durable_line_by_line(self, tmp_path):
        path = tmp_path / "s.jsonl"
        events = list(_log().events)
        append_event(path, events[0])
        assert len(read_session(path)) == 1
        append_event(path, events[1])
        assert len(read_session(path)) == 2

    def test_append_to_existing_file_does_not_duplicate_header(self, tmp_path):
        """A second open-and-write on an existing file must not re-emit the header."""
        path = tmp_path / "s.jsonl"
        events = list(_log().events)
        for event in events:
            append_event(path, event)
        for event in events:
            append_event(path, event)
        lines = path.read_text(encoding="utf-8").splitlines()
        headers = [l for l in lines if "dagi-session-log" in l]
        assert len(headers) == 1


class TestVersionGate:
    def test_a_future_format_is_rejected(self, tmp_path):
        path = tmp_path / "s.jsonl"
        path.write_text(
            json.dumps({"format": 99, "kind": "dagi-session-log"}) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(IncompatibleFormat, match="format 99"):
            read_session(path)

    def test_a_missing_header_is_rejected(self, tmp_path):
        path = tmp_path / "s.jsonl"
        path.write_text('{"seq": 1}\n', encoding="utf-8")
        with pytest.raises(IncompatibleFormat, match="not a session log"):
            read_session(path)

    def test_an_empty_file_reads_as_no_events(self, tmp_path):
        path = tmp_path / "s.jsonl"
        path.touch()
        assert read_session(path) == []

    def test_a_truncated_final_line_is_dropped_not_fatal(self, tmp_path):
        """A crash mid-write leaves a partial line. Recovery must survive it."""
        path = tmp_path / "s.jsonl"
        write_session(path, _log().events)
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"seq": 4, "type": "turn/e')
        assert [e.seq for e in read_session(path)] == [1, 2, 3]


class TestBranchRoundTrip:
    def test_branch_field_survives_write_and_read(self, tmp_path):
        path = tmp_path / "s.jsonl"
        log = SessionLog()
        log.append(ev.REQUEST_HEADER, {"system": "sys", "reason": "initial"})
        log.append(ev.TURN_START, {"turn": 1})
        log.append(ev.STEP_START, {"turn": 1, "step": 1})
        log.append(
            ev.BRANCH_START,
            {"branch": "sub_1", "parent_branch": "main", "turn": 1, "step": 1},
        )
        log.append(ev.TURN_START, {"turn": 1}, branch="sub_1")
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 0, "role": "user", "content": "sub_msg", "source": "human"},
            surface_op="append",
            branch="sub_1",
        )
        write_session(path, log.events)
        events = read_session(path)
        branch_events = [e for e in events if e.branch == "sub_1"]
        assert len(branch_events) == 2
        assert all(e.branch == "sub_1" for e in branch_events)

    def test_main_branch_events_omit_branch_field_in_json(self, tmp_path):
        path = tmp_path / "s.jsonl"
        log = SessionLog()
        log.append(ev.REQUEST_HEADER, {"system": "sys", "reason": "initial"})
        log.append(ev.TURN_START, {"turn": 1})
        write_session(path, log.events)
        lines = path.read_text(encoding="utf-8").splitlines()
        # Skip the header line; check all event lines
        event_lines = lines[1:]
        for line in event_lines:
            if not line.strip():
                continue
            raw = json.loads(line)
            assert "branch" not in raw


class TestOnAppendHook:
    def test_on_append_fires_after_every_commit(self, tmp_path):
        path = tmp_path / "s.jsonl"
        log = SessionLog()
        log.on_append = lambda e: append_event(path, e)

        log.append(ev.REQUEST_HEADER, {"system": "s", "reason": "initial"})
        log.append(ev.TURN_START, {"turn": 1})

        events_on_disk = read_session(path)
        assert [e.type for e in events_on_disk] == [ev.REQUEST_HEADER, ev.TURN_START]

    def test_on_append_sees_a_consistent_log_state(self, tmp_path):
        """The hook fires after _absorb, so seq and surface are already updated."""
        seqs_at_fire: list[int] = []
        log = SessionLog()
        log.on_append = lambda e: seqs_at_fire.append(log.seq)

        log.append(ev.TURN_START, {"turn": 1})
        log.append(ev.STEP_START, {"turn": 1, "step": 1})

        # log.seq must reflect the just-committed event, not the previous one.
        assert seqs_at_fire == [1, 2]

    def test_a_rejected_append_does_not_call_on_append(self, tmp_path):
        """An event that fails validation must never reach the sink."""
        fired: list[bool] = []
        log = SessionLog()
        log.on_append = lambda e: fired.append(True)

        with pytest.raises(Exception):
            log.append("bogus/type", {})

        assert fired == []
