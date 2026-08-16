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
    def test_loop_owns_an_empty_log_at_construction(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert loop.log.seq == 0
        assert loop.log.open_turn is None


class TestTurnBoundaries:
    def test_a_completed_run_opens_and_closes_exactly_one_turn(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _text_response(
            "all done <<END_OF_RESPONSE>>"
        )

        loop.run("do the thing")

        types = [e.type for e in loop.log.events]
        assert types[0] == ev.TURN_START
        assert types[-1] == ev.TURN_END
        assert types.count(ev.TURN_START) == 1
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
