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
from tools.compact._compact import CompactionResult


def _make_loop(project_path: Path, **overrides) -> AgentLoop:
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
        loop = AgentLoop(config=config, _registry=fake_registry, _tracker=fake_tracker)
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


class TestShadowEquality:
    """The derived surface must reproduce _messages exactly, board excluded."""

    def test_text_only_conversation_matches(self, tmp_path):
        loop = _make_loop(tmp_path, shadow_check=True)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "done <<END_OF_RESPONSE>>"
        )
        loop.run("go")
        loop._shadow_check()

    def test_multi_step_conversation_with_tools_matches(self, tmp_path):
        loop = _make_loop(tmp_path, shadow_check=True, max_continuations=2)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _tool_response("read", '{"file_path": "a.txt"}', call_id="c1"),
            _tool_response("read", '{"file_path": "b.txt"}', call_id="c2"),
            _text_response("done <<END_OF_RESPONSE>>"),
        ]
        loop.registry.dispatch = MagicMock(return_value="contents")
        loop.run("go")
        loop._shadow_check()

    def test_continuation_injection_matches(self, tmp_path):
        loop = _make_loop(tmp_path, shadow_check=True, max_continuations=2)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _text_response("thinking"),
            _text_response("still thinking"),
            _text_response("done <<END_OF_RESPONSE>>"),
        ]
        loop.run("go")
        loop._shadow_check()

    def test_the_harness_actually_detects_divergence(self, tmp_path):
        """A check that cannot fail is worthless. Prove this one can."""
        from agent.session_log import InvariantError

        loop = _make_loop(tmp_path, shadow_check=True)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "done <<END_OF_RESPONSE>>"
        )
        loop.run("go")
        loop._messages.append({"role": "user", "content": "smuggled in"})

        with pytest.raises(InvariantError, match="shadow divergence"):
            loop._shadow_check()

    def test_the_status_board_is_excluded_from_both_sides(self, tmp_path):
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


def _compaction(summary: str, head_end: int, tail_start: int) -> CompactionResult:
    """A CompactionResult describing a replacement that already happened."""
    return CompactionResult(
        did_compact=True,
        removed_count=tail_start - head_end,
        summary_input_tokens=0,
        summary_output_tokens=0,
        summary_cost=None,
        summary_content=summary,
        head_end=head_end,
        tail_start=tail_start,
    )


class TestCompactionEvent:
    """Compaction shadows surface nodes; it never deletes log events."""

    def _loop_with_history(self, tmp_path, exchanges: int = 6):
        loop = _make_loop(tmp_path)
        loop.log.append(ev.TURN_START, {"turn": 1})
        for i in range(exchanges):
            loop._log_user_message("user", f"question {i}", "human")
            loop.log.append(
                ev.ASSISTANT_MESSAGE,
                {"message": {"role": "assistant", "content": f"answer {i}"}},
                surface_op="append",
            )
        loop._messages[1:] = loop.log.derive_messages()
        return loop

    def test_compaction_replaces_the_shadowed_span(self, tmp_path):
        loop = self._loop_with_history(tmp_path)
        before = len(loop.log.derive_messages())

        loop._log_compaction(_compaction("[CONTEXT SUMMARY] earlier chat", 1, 5))

        derived = loop.log.derive_messages()
        assert len(derived) == before - 4 + 1
        assert derived[0] == {
            "role": "user", "content": "[CONTEXT SUMMARY] earlier chat",
        }

    def test_compaction_bumps_the_surface_generation(self, tmp_path):
        loop = self._loop_with_history(tmp_path)
        assert loop.log.surface.generation == 0
        loop._log_compaction(_compaction("s", 1, 3))
        assert loop.log.surface.generation == 1

    def test_compaction_cites_every_node_it_shadows(self, tmp_path):
        loop = self._loop_with_history(tmp_path)
        shadowed = list(loop.log.surface.nodes[:4])

        loop._log_compaction(_compaction("s", 1, 5))

        event = loop.log.events[-1]
        assert set(shadowed) <= set(event.source_seqs)

    def test_the_raw_log_keeps_the_compacted_events(self, tmp_path):
        """Append-only: shadowed events are hidden from the surface, not lost."""
        loop = self._loop_with_history(tmp_path)
        before = len(loop.log.events)
        loop._log_compaction(_compaction("s", 1, 5))
        assert len(loop.log.events) == before + 1

    def test_a_no_op_compaction_logs_nothing(self, tmp_path):
        loop = self._loop_with_history(tmp_path)
        before = len(loop.log.events)
        loop._log_compaction(CompactionResult(
            did_compact=False, removed_count=0,
            summary_input_tokens=0, summary_output_tokens=0, summary_cost=None,
        ))
        assert len(loop.log.events) == before

    def test_a_span_past_the_end_of_the_surface_is_rejected(self, tmp_path):
        """Silent truncation here would corrupt the surface irrecoverably."""
        from agent.session_log import InvariantError

        loop = self._loop_with_history(tmp_path, exchanges=2)
        with pytest.raises(InvariantError, match="outside a surface"):
            loop._log_compaction(_compaction("s", 1, 99))

    def test_a_real_compaction_keeps_the_shadow_in_step(self, tmp_path):
        """End-to-end: CompactTool mutates _messages, the log tracks it."""
        loop = self._loop_with_history(tmp_path)
        loop.compact_tool.bind(loop._messages, loop.config, loop.client)
        loop.client = MagicMock()
        loop.compact_tool._client = loop.client
        loop.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="a recap"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, cost=None),
        )

        loop.compact(force=True)

        loop._shadow_check()
