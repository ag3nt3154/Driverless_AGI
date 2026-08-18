"""tests/test_session_log_shadow.py — Phase-1 shadow log verification.

During Phase 1 the event log runs alongside AgentLoop._messages, which stays
authoritative. These tests prove the log's vocabulary is complete and its
projection faithful BEFORE anything is allowed to depend on it.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent import session_events as ev
from agent.loop import AgentConfig, AgentLoop
from agent.session_log import is_status_board
from agent.loop import CompactionResult


def _make_loop(project_path: Path, _initial: list | None = None, **overrides) -> AgentLoop:
    config = AgentConfig(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        project_path=project_path,
        **overrides,
    )
    fake_registry = MagicMock()
    fake_registry.get_openai_tools_list.return_value = []
    fake_registry.list_tools.return_value = []
    fake_registry._tools = {}
    fake_tracker = MagicMock()

    with (
        patch("openai.OpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        loop = AgentLoop(
            config=config,
            initial_messages=_initial,
            _registry=fake_registry,
            _tracker=fake_tracker,
        )
    loop.tracker = fake_tracker
    loop.registry = fake_registry
    loop._skip_slug_generation = True
    return loop


def _text_response(content: str) -> SimpleNamespace:
    """A completion with no tool calls."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content=content))],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            cost=None,
            completion_tokens_details=None,
            prompt_tokens_details=None,
        ),
    )


class TestLogConstruction:
    def test_loop_owns_a_log_holding_only_the_initial_header(self, tmp_path):
        """Construction logs the request envelope and nothing else — no turn
        is open, and the envelope costs zero surface nodes."""
        loop = _make_loop(tmp_path)
        assert [e.type for e in loop.log.events] == [ev.REQUEST_HEADER]
        assert loop.log.open_turn is None
        assert loop.log.derive_messages() == []


class TestTurnBoundaries:
    def test_a_completed_run_opens_and_closes_exactly_one_turn(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "all done <<END_OF_RESPONSE>>"
        )

        loop.run("do the thing")

        types = [e.type for e in loop.log.events]
        # The initial request/header precedes the turn, so compare only the
        # turn-bracket events themselves.
        assert [t for t in types if t in (ev.TURN_START, ev.TURN_END)] == [
            ev.TURN_START, ev.TURN_END
        ]
        assert types[-1] == ev.TURN_END
        assert loop.log.open_turn is None

    def test_completed_run_records_the_completed_reason(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "done <<END_OF_RESPONSE>>"
        )

        loop.run("go")

        assert loop.log.events[-1].data["reason"] == ev.reason_completed()

    def test_hitting_max_continuations_records_that_reason(self, tmp_path):
        loop = _make_loop(tmp_path, max_continuations=0)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response("still working")

        loop.run("go")

        assert loop.log.events[-1].data["reason"] == ev.reason_max_continuations()

    def test_a_second_run_opens_turn_two(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "done <<END_OF_RESPONSE>>"
        )

        loop.run("first")
        loop.run("second")

        starts = [e.data["turn"] for e in loop.log.events if e.type == ev.TURN_START]
        assert starts == [1, 2]

    def test_an_exception_closes_the_turn_with_an_error_reason(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = RuntimeError("kaboom")

        with pytest.raises(RuntimeError):
            loop.run("go")

        assert loop.log.open_turn is None
        assert loop.log.events[-1].data["reason"]["kind"] == "error"
        assert "kaboom" in loop.log.events[-1].data["reason"]["error"]["message"]


class TestUserMessageEvents:
    def test_the_task_prompt_is_logged_as_a_human_user_message(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "done <<END_OF_RESPONSE>>"
        )

        loop.run("build the widget")

        users = [e for e in loop.log.events if e.type == ev.USER_MESSAGE]
        assert users[0].data["role"] == "user"
        assert users[0].data["content"] == "build the widget"
        assert users[0].data["source"] == "human"
        assert users[0].data["step"] == 0  # turn entry, before the first step

    def test_user_messages_are_surface_events(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "done <<END_OF_RESPONSE>>"
        )

        loop.run("go")

        users = [e for e in loop.log.events if e.type == ev.USER_MESSAGE]
        assert all(e.surface_op == "append" for e in users)

    def test_continuation_prompt_is_logged_with_its_own_source(self, tmp_path):
        from agent.loop import CONTINUE_PROMPT

        loop = _make_loop(tmp_path, max_continuations=1)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _text_response("thinking out loud"),
            _text_response("done <<END_OF_RESPONSE>>"),
        ]

        loop.run("go")

        sources = [e.data["source"] for e in loop.log.events if e.type == ev.USER_MESSAGE]
        assert sources == ["human", "continue"]
        cont = [e for e in loop.log.events if e.data.get("source") == "continue"][0]
        assert cont.data["content"] == CONTINUE_PROMPT


def _tool_response(name: str, arguments: str, call_id: str = "c1") -> SimpleNamespace:
    tc = SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tc], content=None))],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            cost=None,
            completion_tokens_details=None,
            prompt_tokens_details=None,
        ),
    )


class TestStepBoundaries:
    def test_each_api_turn_is_one_bracketed_step(self, tmp_path):
        loop = _make_loop(tmp_path, max_continuations=1)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _text_response("working"),
            _text_response("done <<END_OF_RESPONSE>>"),
        ]

        loop.run("go")

        starts = [e for e in loop.log.events if e.type == ev.STEP_START]
        ends = [e for e in loop.log.events if e.type == ev.STEP_END]
        assert [e.data["step"] for e in starts] == [1, 2]
        assert len(ends) == len(starts)

    def test_steps_are_numbered_within_their_turn(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "done <<END_OF_RESPONSE>>"
        )

        loop.run("first")
        loop.run("second")

        starts = [(e.data["turn"], e.data["step"]) for e in loop.log.events
                  if e.type == ev.STEP_START]
        assert starts == [(1, 1), (2, 1)]


class TestAssistantAndToolEvents:
    def test_text_only_reply_is_logged_as_a_surface_assistant_message(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "done <<END_OF_RESPONSE>>"
        )

        loop.run("go")

        asst = [e for e in loop.log.events if e.type == ev.ASSISTANT_MESSAGE]
        assert len(asst) == 1
        assert asst[0].surface_op == "append"
        assert asst[0].data["message"]["role"] == "assistant"

    def test_tool_call_is_logged_before_dispatch_runs(self, tmp_path):
        """Crash-safety: a call recorded before execution is detectable as
        interrupted; an unrecorded call is indistinguishable from never-ran."""
        seen_at_dispatch: list[list[str]] = []
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _tool_response("read", '{"file_path": "a.txt"}'),
            _text_response("done <<END_OF_RESPONSE>>"),
        ]

        def _spy(name, args):
            seen_at_dispatch.append([e.type for e in loop.log.events])
            return "file contents"

        loop.registry.dispatch = _spy
        loop.run("go")

        assert ev.TOOL_CALL in seen_at_dispatch[0]
        assert ev.TOOL_RESULT not in seen_at_dispatch[0]

    def test_tool_call_stores_the_raw_unparsed_arguments(self, tmp_path):
        """Re-serialising a parsed dict changes key order and whitespace,
        which changes the token stream and therefore the cache prefix."""
        raw = '{"file_path":   "a.txt", "offset": 1}'
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _tool_response("read", raw),
            _text_response("done <<END_OF_RESPONSE>>"),
        ]
        loop.registry.dispatch = MagicMock(return_value="ok")

        loop.run("go")

        call = [e for e in loop.log.events if e.type == ev.TOOL_CALL][0]
        assert call.data["arguments"] == raw

    def test_tool_result_pairs_with_its_call(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _tool_response("read", "{}", call_id="abc"),
            _text_response("done <<END_OF_RESPONSE>>"),
        ]
        loop.registry.dispatch = MagicMock(return_value="ok")

        loop.run("go")

        result = [e for e in loop.log.events if e.type == ev.TOOL_RESULT][0]
        assert result.data["call_id"] == "abc"
        assert result.surface_op == "append"


class TestDerivationHolds:
    """What the Phase-1 shadow harness used to assert, kept as end-to-end cover.

    The harness itself is gone — once _messages is *computed from* the log,
    asserting they agree is a tautology. These exercise the same conversation
    shapes through run() and check the derivation end to end instead.
    """

    def test_text_only_conversation_matches(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "done <<END_OF_RESPONSE>>"
        )
        loop.run("go")
        assert loop._messages[1:] == loop.log.derive_messages()

    def test_multi_step_conversation_with_tools_matches(self, tmp_path):
        loop = _make_loop(tmp_path, max_continuations=2)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _tool_response("read", '{"file_path": "a.txt"}', call_id="c1"),
            _tool_response("read", '{"file_path": "b.txt"}', call_id="c2"),
            _text_response("done <<END_OF_RESPONSE>>"),
        ]
        loop.registry.dispatch = MagicMock(return_value="contents")
        loop.run("go")
        assert [m["role"] for m in loop._messages] == [
            "system", "user", "assistant", "tool", "assistant", "tool", "assistant",
        ]

    def test_continuation_injection_matches(self, tmp_path):
        loop = _make_loop(tmp_path, max_continuations=2)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _text_response("thinking"),
            _text_response("still thinking"),
            _text_response("done <<END_OF_RESPONSE>>"),
        ]
        loop.run("go")
        assert loop._messages[1:] == loop.log.derive_messages()

    def test_the_status_board_predicate_still_identifies_a_board(self, tmp_path):
        assert is_status_board({"role": "system", "content": "## Session Context\nx"})
        assert not is_status_board({"role": "system", "content": "wiki index"})
        assert not is_status_board({"role": "user", "content": "## Session Context"})


class TestRequestHeader:
    def test_construction_emits_an_initial_header(self, tmp_path):
        loop = _make_loop(tmp_path)
        header = loop.log.latest_header()
        assert header is not None
        assert header["reason"] == "initial"
        assert header["system"] == loop._messages[0]["content"]

    def test_header_records_the_tool_surface(self, tmp_path):
        loop = _make_loop(tmp_path)
        header = loop.log.latest_header()
        assert header["tool_names"] == sorted(header["tool_names"])
        assert len(header["tools_digest"]) == 64

    def test_header_message_reproduces_messages_zero(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert loop._header_message() == loop._messages[0]

    def test_leaving_plan_mode_emits_a_change_header(self, tmp_path):
        loop = _make_loop(tmp_path, plan_mode=True)
        before = len([e for e in loop.log.events if e.type == ev.REQUEST_HEADER])
        loop._rebuild_for_normal_mode(Path(__file__).resolve().parents[1])
        headers = [e for e in loop.log.events if e.type == ev.REQUEST_HEADER]
        assert len(headers) == before + 1
        assert headers[-1].data["reason"] == "change"
        assert headers[-1].data["system"] == loop._messages[0]["content"]


class TestEphemeralBoard:
    """The plan status board is rendered per request, never stored.

    Storing it made the reusable request prefix end wherever the board last
    sat — roughly one full step behind the tail. Rendering it as a trailing
    message keeps everything before it byte-identical between steps.
    """

    def test_board_is_not_a_member_of_messages(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._refresh_dynamic_context()
        assert not any(is_status_board(m) for m in loop._messages)

    def test_request_messages_end_with_the_board(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._refresh_dynamic_context()
        request = loop._build_request_messages()
        assert is_status_board(request[-1])
        assert request[0] == loop._header_message()

    def test_request_prefix_is_stable_across_refreshes(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._refresh_dynamic_context()
        first = loop._build_request_messages()
        loop._messages.append({"role": "user", "content": "next"})
        loop._refresh_dynamic_context()
        second = loop._build_request_messages()
        # Everything the first request sent, minus its trailing board, is an
        # exact prefix of the second request. This is the cache guarantee.
        assert second[: len(first) - 1] == first[:-1]

    def test_unchanged_board_logs_no_second_plan_write(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._refresh_dynamic_context()
        loop._refresh_dynamic_context()
        writes = [e for e in loop.log.events if e.type == ev.PLAN_WRITE]
        assert len(writes) == 1

    def test_changed_board_logs_a_second_plan_write(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._refresh_dynamic_context()
        loop.config.python_env = "some-other-env"
        loop._refresh_dynamic_context()
        writes = [e for e in loop.log.events if e.type == ev.PLAN_WRITE]
        assert len(writes) == 2
        assert "some-other-env" in writes[-1].data["board"]


def _compaction(summary: str, removed_count: int = 4) -> CompactionResult:
    """A CompactionResult describing a replacement that already happened."""
    return CompactionResult(
        did_compact=True,
        generation=1,
        removed_count=removed_count,
        summary_content=summary,
    )


class TestCompactionEvent:
    """Compaction shadows surface nodes; it never deletes log events."""

    def _loop_with_history(self, tmp_path, exchanges: int = 6):
        """Build a loop with `exchanges` steps on turn 1.

        Each step has one user message and one assistant message on the surface.
        Steps are indexed 0..(exchanges-1) on turn 1.
        """
        loop = _make_loop(tmp_path)
        loop.log.append(ev.TURN_START, {"turn": 1})
        for i in range(exchanges):
            loop.log.append(ev.STEP_START, {"turn": 1, "step": i})
            loop._log_user_message("user", f"question {i}", "human")
            loop.log.append(
                ev.ASSISTANT_MESSAGE,
                {"turn": 1, "step": i, "message": {"role": "assistant", "content": f"answer {i}"}},
                surface_op="append",
            )
            loop.log.append(ev.STEP_END, {"turn": 1, "step": i})
        loop.log.append(ev.TURN_END, {"turn": 1, "reason": {"kind": "completed"}})
        loop._sync_messages()
        return loop

    def _with_turn(self, loop, fn):
        """Open a synthetic turn, call fn(), then close the turn."""
        t = loop.log.next_turn()
        loop.log.append(ev.TURN_START, {"turn": t})
        try:
            fn()
        finally:
            loop.log.append(ev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

    def test_compaction_replaces_the_shadowed_span(self, tmp_path):
        loop = self._loop_with_history(tmp_path)
        before = len(loop.log.derive_messages())

        # Shadow steps 0 and 1 (4 surface nodes); tail starts at step (1, 2)
        self._with_turn(loop, lambda: loop._log_compaction(
            _compaction("[CONTEXT SUMMARY] earlier chat", removed_count=4), (1, 2)
        ))

        derived = loop.log.derive_messages()
        assert len(derived) == before - 4 + 1
        assert derived[0] == {
            "role": "user", "content": "[CONTEXT SUMMARY] earlier chat",
        }

    def test_compaction_bumps_the_surface_generation(self, tmp_path):
        loop = self._loop_with_history(tmp_path)
        assert loop.log.surface.generation == 0
        # Shadow step 0 (2 nodes); tail starts at step (1, 1)
        self._with_turn(loop, lambda: loop._log_compaction(
            _compaction("s", removed_count=2), (1, 1)
        ))
        assert loop.log.surface.generation == 1

    def test_compaction_cites_every_node_it_shadows(self, tmp_path):
        loop = self._loop_with_history(tmp_path)
        shadowed = list(loop.log.surface.nodes[:4])

        # Shadow steps 0 and 1 (4 nodes); tail starts at step (1, 2)
        self._with_turn(loop, lambda: loop._log_compaction(
            _compaction("s", removed_count=4), (1, 2)
        ))

        event = next(e for e in reversed(loop.log.events) if e.type == ev.CONTEXT_COMPACTION)
        assert set(shadowed) <= set(event.source_seqs)

    def test_the_raw_log_keeps_the_compacted_events(self, tmp_path):
        """Append-only: shadowed events are hidden from the surface, not lost."""
        loop = self._loop_with_history(tmp_path)
        before = len(loop.log.events)
        self._with_turn(loop, lambda: loop._log_compaction(
            _compaction("s", removed_count=4), (1, 2)
        ))
        # +1 for CONTEXT_COMPACTION, +2 for TURN_START/TURN_END from _with_turn
        assert len(loop.log.events) == before + 3

    def test_a_no_op_compaction_logs_nothing(self, tmp_path):
        loop = self._loop_with_history(tmp_path)
        before = len(loop.log.events)
        # tail_first_step is irrelevant when did_compact=False; no turn needed
        loop._log_compaction(CompactionResult(did_compact=False), (1, 0))
        assert len(loop.log.events) == before

    def test_a_span_past_the_end_of_the_surface_is_rejected(self, tmp_path):
        """A step that does not exist on the surface raises InvariantError."""
        from agent.session_log import InvariantError

        loop = self._loop_with_history(tmp_path, exchanges=2)
        # Step (1, 99) does not exist in the log
        t = loop.log.next_turn()
        loop.log.append(ev.TURN_START, {"turn": t})
        try:
            with pytest.raises(InvariantError, match="not found on surface"):
                loop._log_compaction(_compaction("s"), (1, 99))
        finally:
            loop.log.append(ev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

    def test_a_real_compaction_keeps_the_shadow_in_step(self, tmp_path):
        """End-to-end: subagent compaction writes a surface CONTEXT_COMPACTION event
        and the derived messages match the log projection."""
        from pathlib import Path
        from unittest.mock import patch, MagicMock

        loop = self._loop_with_history(tmp_path)
        loop._last_prompt_tokens = 5_000
        loop.config.keep_recent_tokens = 1_000

        # compact() guards on _last_request_snapshot being set
        loop._last_request_snapshot = {
            "model": "test-model",
            "messages": [{"role": "system", "content": "You are a test agent."}],
            "tools": [],
            "parallel_tool_calls": False,
            "extra_body": {},
            "base_url": "",
        }

        handoff_path = tmp_path / "compact_test.md"

        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "a recap"
        mock_result.handoff_path = handoff_path

        # compact() needs an open turn to log CONTEXT_COMPACTION
        t = loop.log.next_turn()
        loop.log.append(ev.TURN_START, {"turn": t})
        with patch("agent.loop.run_subagent", return_value=mock_result):
            result = loop.compact(force=True)
        loop.log.append(ev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        assert result.did_compact is True
        assert loop._messages[1:] == loop.log.derive_messages()


class TestDerivedMessages:
    """Task 14: _messages is a cache of the log, not a parallel truth."""

    def test_sync_reproduces_header_plus_surface(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.log.append(ev.TURN_START, {"turn": 1})
        loop._log_user_message("user", "hello", "human")
        loop._sync_messages()
        assert loop._messages == [
            loop._header_message(),
            {"role": "user", "content": "hello"},
        ]

    def test_sync_preserves_list_identity_for_the_compact_binding(self, tmp_path):
        """AgentLoop.compact() operates on self._messages in-place.
        Rebinding the attribute would leave it writing to an orphan."""
        loop = _make_loop(tmp_path)
        original = loop._messages
        loop.log.append(ev.TURN_START, {"turn": 1})
        loop._log_user_message("user", "hello", "human")
        loop._sync_messages()
        assert loop._messages is original

    def test_logging_a_user_message_syncs_immediately(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.log.append(ev.TURN_START, {"turn": 1})
        loop._log_user_message("user", "hello", "human")
        assert loop._messages[-1] == {"role": "user", "content": "hello"}

    def test_a_full_tool_using_run_derives_the_same_history(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _tool_response("read", '{"file_path": "x"}'),
            _text_response("done <<END_OF_RESPONSE>>"),
        ]
        loop.registry.dispatch = MagicMock(return_value="contents")
        loop.run("do the thing")
        assert loop._messages == [loop._header_message()] + loop.log.derive_messages()

    def test_shadow_check_is_gone(self, tmp_path):
        """The harness proved log == _messages; now it is a tautology."""
        loop = _make_loop(tmp_path)
        assert not hasattr(loop, "_shadow_check")

    def test_injected_message_reaches_the_log(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.log.append(ev.TURN_START, {"turn": 1})
        loop.inject_and_resume("do this instead")
        assert loop._messages[-1] == {"role": "user", "content": "do this instead"}
        assert loop.log.events[-1].data["source"] == "inject"

    def test_reload_notice_reaches_the_log(self, tmp_path):
        """/reload short-circuits before the normal turn, so it opens its own."""
        loop = _make_loop(tmp_path)
        loop._rebuild_for_reload = MagicMock(return_value=(["a"], [], []))

        notice = loop.run("/reload")

        assert loop._messages[-1] == {"role": "system", "content": notice}
        assert loop.log.open_turn is None


class TestResumeSeeding:
    """A resumed session must not lose its history when authority flips.

    _messages used to be seeded straight from initial_messages. Now that it is
    derived, those messages have to enter the log or they simply vanish.
    """

    HISTORY = [
        {"role": "system", "content": "old system prompt"},
        {"role": "user", "content": "earlier question"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "seed-1",
                "type": "function",
                "function": {"name": "read", "arguments": '{"file_path": "a"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "seed-1", "content": "file body"},
        {"role": "assistant", "content": "earlier answer"},
    ]

    def test_resumed_history_survives_derivation(self, tmp_path):
        loop = _make_loop(tmp_path, _initial=self.HISTORY)
        assert loop._messages[1:] == self.HISTORY[1:]

    def test_the_system_prompt_is_refreshed_not_replayed(self, tmp_path):
        """Resuming must pick up an edited AGENTS.md, not the stale prompt."""
        loop = _make_loop(tmp_path, _initial=self.HISTORY)
        assert loop._messages[0]["content"] != "old system prompt"
        assert loop._messages[0] == loop._header_message()

    def test_the_seed_is_marked_closed(self, tmp_path):
        """Later turns must not be able to append into replayed history."""
        loop = _make_loop(tmp_path, _initial=self.HISTORY)
        assert loop.log.events[-1].type == ev.END_SEED
        assert loop.log.open_turn is None
        assert loop.log.next_turn() == 1

    def test_a_fresh_session_seeds_nothing(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert [e.type for e in loop.log.events] == [ev.REQUEST_HEADER]
