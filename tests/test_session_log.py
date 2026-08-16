"""tests/test_session_log.py — Session event vocabulary and append-only log."""
from __future__ import annotations

import pytest

from agent import session_events as ev


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
