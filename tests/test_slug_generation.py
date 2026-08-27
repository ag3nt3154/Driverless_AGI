"""tests/test_slug_generation.py — Tests for session slug generation in AgentLoop."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class TestGenerateSessionSlug:
    """_generate_session_slug makes an LLM side-call to name the session.

    This matters because unnamed session files are hard to find in history.
    A failed slug call must never crash the agent loop — silence is correct.
    """

    def _make_loop(self, tmp_path, slug_response="fix_login_bug"):
        from agent.loop import AgentLoop, AgentConfig

        config = AgentConfig(
            model="test-model",
            api_key="fake",
            base_url="http://localhost:1234/v1",
            project_path=tmp_path,
        )
        mock_choice = MagicMock()
        mock_choice.message.content = slug_response
        mock_choice.message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = SimpleNamespace(
            prompt_tokens=20, completion_tokens=5, cost=None
        )
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent.loop.SessionTracker", MagicMock())
            loop = AgentLoop(config)
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = mock_response
        return loop

    def test_returns_slug_from_llm(self, tmp_path):
        """Slug returned by the LLM is passed through unchanged."""
        loop = self._make_loop(tmp_path, slug_response="fix_login_bug")
        result = loop._generate_session_slug("Please fix the login bug")
        assert result == "fix_login_bug"

    def test_returns_none_on_api_error(self, tmp_path):
        """API failure must return None rather than propagating the exception."""
        loop = self._make_loop(tmp_path)
        loop.client.chat.completions.create.side_effect = Exception("timeout")
        result = loop._generate_session_slug("some task")
        assert result is None

    def test_returns_none_on_empty_response(self, tmp_path):
        """Empty LLM response (whitespace / no content) must return None."""
        loop = self._make_loop(tmp_path, slug_response="")
        result = loop._generate_session_slug("some task")
        assert result is None

    def test_slug_truncates_message_to_500_chars(self, tmp_path):
        """The side-call must not send more than 500 chars of the first message."""
        loop = self._make_loop(tmp_path, slug_response="long_task_slug")
        long_message = "x" * 1000
        loop._generate_session_slug(long_message)
        call_kwargs = loop.client.chat.completions.create.call_args
        user_msg = call_kwargs.kwargs["messages"][1]["content"]
        assert len(user_msg) <= 500

    def test_slug_uses_correct_system_prompt(self, tmp_path):
        """The side-call must send _SLUG_SYSTEM as the system message."""
        from agent.loop import AgentLoop

        loop = self._make_loop(tmp_path)
        loop._generate_session_slug("some task")
        call_kwargs = loop.client.chat.completions.create.call_args
        system_msg = call_kwargs.kwargs["messages"][0]["content"]
        assert system_msg == AgentLoop._SLUG_SYSTEM


class TestSkipSlugGeneration:
    """_skip_slug_generation controls whether slug naming runs in run().

    When True (resumed session), slug generation is skipped — the session
    already has a name. When False (fresh session), the slug side-call fires.
    """

    def test_false_when_no_initial_messages(self, tmp_path):
        """Fresh sessions must have _skip_slug_generation == False."""
        from agent.loop import AgentLoop, AgentConfig

        config = AgentConfig(
            model="test-model",
            api_key="fake",
            base_url="http://localhost:1234/v1",
            project_path=tmp_path,
        )
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent.loop.SessionTracker", MagicMock())
            loop = AgentLoop(config)
        assert loop._skip_slug_generation is False

    def test_true_when_initial_messages_provided(self, tmp_path):
        """Resumed sessions must have _skip_slug_generation == True."""
        from agent.loop import AgentLoop, AgentConfig

        config = AgentConfig(
            model="test-model",
            api_key="fake",
            base_url="http://localhost:1234/v1",
            project_path=tmp_path,
        )
        initial = [{"role": "user", "content": "prior task"}]
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent.loop.SessionTracker", MagicMock())
            loop = AgentLoop(config, initial_messages=initial)
        assert loop._skip_slug_generation is True


class TestSlugWiredIntoRun:
    """Slug generation is called from run() and passed to tracker.rename_with_slug.

    This wires the two pieces together: slug generated → session file renamed.
    """

    def _make_loop_for_run(self, tmp_path):
        import json
        from agent.loop import AgentLoop, AgentConfig

        config = AgentConfig(
            model="test-model",
            api_key="fake",
            base_url="http://localhost:1234/v1",
            project_path=tmp_path,
        )
        fake_tracker = MagicMock()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent.loop.SessionTracker", MagicMock(return_value=fake_tracker))
            loop = AgentLoop(config)

        loop.tracker = fake_tracker

        # Minimal LLM response that ends the session via write_handoff tool call
        _wh_tc = SimpleNamespace(
            id="tc_end",
            function=SimpleNamespace(
                name="write_handoff", arguments=json.dumps({"content": "Done."})
            ),
        )
        end_response = MagicMock()
        end_choice = MagicMock()
        end_choice.message.content = None
        end_choice.message.tool_calls = [_wh_tc]
        # MagicMock auto-creates any attribute; without these two the loop
        # would copy a Mock into the assistant message, which is not JSON data.
        end_choice.message.reasoning_content = None
        end_choice.message.model_extra = {}
        end_response.choices = [end_choice]
        end_response.usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, cost=None,
            completion_tokens_details=None,
        )
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = end_response
        return loop

    def test_rename_with_slug_called_on_fresh_session(self, tmp_path):
        """run() must call tracker.rename_with_slug when slug is successfully generated."""
        loop = self._make_loop_for_run(tmp_path)
        # Patch _generate_session_slug to return a known slug
        loop._generate_session_slug = MagicMock(return_value="add_dark_mode")
        loop.run("Add dark mode support")
        loop.tracker.rename_with_slug.assert_called_once_with("add_dark_mode")

    def test_rename_not_called_when_slug_is_none(self, tmp_path):
        """run() must NOT call rename_with_slug when slug generation fails."""
        loop = self._make_loop_for_run(tmp_path)
        loop._generate_session_slug = MagicMock(return_value=None)
        loop.run("Add dark mode support")
        loop.tracker.rename_with_slug.assert_not_called()

    def test_rename_not_called_when_skip_slug_generation(self, tmp_path):
        """run() must NOT generate or apply a slug when resuming from history."""
        import json
        from agent.loop import AgentLoop, AgentConfig

        config = AgentConfig(
            model="test-model",
            api_key="fake",
            base_url="http://localhost:1234/v1",
            project_path=tmp_path,
        )
        fake_tracker = MagicMock()
        initial = [{"role": "system", "content": "sys"}, {"role": "user", "content": "prior"}]

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent.loop.SessionTracker", MagicMock(return_value=fake_tracker))
            loop = AgentLoop(config, initial_messages=initial)

        loop.tracker = fake_tracker

        _wh_tc = SimpleNamespace(
            id="tc_end",
            function=SimpleNamespace(
                name="write_handoff", arguments=json.dumps({"content": "Done."})
            ),
        )
        end_response = MagicMock()
        end_choice = MagicMock()
        end_choice.message.content = None
        end_choice.message.tool_calls = [_wh_tc]
        # MagicMock auto-creates any attribute; without these two the loop
        # would copy a Mock into the assistant message, which is not JSON data.
        end_choice.message.reasoning_content = None
        end_choice.message.model_extra = {}
        end_response.choices = [end_choice]
        end_response.usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, cost=None,
            completion_tokens_details=None,
        )
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = end_response

        gen_mock = MagicMock(return_value="should_not_be_called")
        loop._generate_session_slug = gen_mock
        loop.run("Continue from prior")
        gen_mock.assert_not_called()
        loop.tracker.rename_with_slug.assert_not_called()
