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
