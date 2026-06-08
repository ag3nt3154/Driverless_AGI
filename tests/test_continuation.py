"""tests/test_continuation.py — Unit tests for loop termination flags."""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from agent.loop import AgentConfig, AgentCallbacks, AgentLoop, TASK_END_FLAG, AWAIT_USER_FLAG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(content: str, tool_calls=None):
    """Build a minimal fake OpenAI chat completion response."""
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        cost=None,
        completion_tokens_details=None,
    )
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls or [],
        model_extra={},
    )
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_loop(max_continuations: int = 3) -> AgentLoop:
    """Create an AgentLoop with all heavy dependencies mocked out."""
    config = AgentConfig(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        max_continuations=max_continuations,
    )

    fake_registry = MagicMock()
    fake_registry.get_openai_tools_list.return_value = []
    fake_registry.list_tools.return_value = []

    fake_tracker = MagicMock()
    fake_tracker.record_system = MagicMock()
    fake_tracker.record_user = MagicMock()
    fake_tracker.record_assistant = MagicMock()

    # Patch soul.md and agents.md to not exist, and OpenAI client
    with (
        patch("agent.loop.SessionTracker", return_value=fake_tracker),
        patch("openai.OpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        loop = AgentLoop(
            config=config,
            _registry=fake_registry,
            _tracker=fake_tracker,
        )

    loop.tracker = fake_tracker
    loop.registry = fake_registry
    return loop


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTaskEndFlag:
    def test_flag_triggers_clean_return(self):
        """<<TASK_END>> in the response should be stripped before returning."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _make_response(
            f"All done! {TASK_END_FLAG}"
        )

        result = loop.run("do something")

        assert TASK_END_FLAG not in result
        assert "All done!" in result

    def test_flag_stripped_from_middle(self):
        """Flag can appear anywhere in the response."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _make_response(
            f"Done {TASK_END_FLAG} with extra text"
        )

        result = loop.run("do something")

        assert TASK_END_FLAG not in result
        assert "Done" in result

    def test_no_flag_injects_continue(self):
        """Without <<TASK_END>>, the harness should inject 'continue' and loop."""
        loop = _make_loop(max_continuations=1)
        loop.client = MagicMock()

        # First call: no flag → triggers continuation
        # Second call: has flag → clean return
        loop.client.chat.completions.create.side_effect = [
            _make_response("Still working..."),
            _make_response(f"Finished. {TASK_END_FLAG}"),
        ]

        result = loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 2
        assert TASK_END_FLAG not in result
        assert "Finished." in result

    def test_continue_message_appended_to_history(self):
        """A continuation user message must appear in _messages after an incomplete response."""
        from agent.loop import CONTINUE_PROMPT
        loop = _make_loop(max_continuations=1)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response("Still working..."),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("do something")

        roles = [m["role"] for m in loop._messages]
        assert "user" in roles
        continue_msgs = [m for m in loop._messages if m.get("content") == CONTINUE_PROMPT]
        assert len(continue_msgs) == 1

    def test_safety_valve_exits_at_max_continuations(self):
        """After max_continuations injections, the loop must exit without <<TASK_END>>."""
        max_cont = 2
        loop = _make_loop(max_continuations=max_cont)
        loop.client = MagicMock()

        # Always return without the flag
        loop.client.chat.completions.create.return_value = _make_response("Still stuck.")

        result = loop.run("do something")

        # Should have called the API max_cont + 1 times (initial + max_cont continuations)
        assert loop.client.chat.completions.create.call_count == max_cont + 1
        assert result == "Still stuck."

    def test_continuation_count_increments(self):
        """_continuation_count must reflect how many continuations happened."""
        loop = _make_loop(max_continuations=3)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response("Step 1"),
            _make_response("Step 2"),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("do something")

        assert loop._continuation_count == 2

    def test_on_done_fires_with_clean_result(self):
        """on_done callback must receive the stripped result, not the raw flag."""
        done_results = []
        callbacks = AgentCallbacks(on_done=lambda r: done_results.append(r))

        loop = _make_loop()
        loop.client = MagicMock()
        loop.callbacks = callbacks
        loop.client.chat.completions.create.return_value = _make_response(
            f"Task complete. {TASK_END_FLAG}"
        )

        loop.run("do something")

        assert len(done_results) == 1
        assert TASK_END_FLAG not in done_results[0]


class TestWaitForUserFlag:
    def test_wait_flag_exits_loop_cleanly(self):
        """<<WAIT_FOR_USER_RESPONSE>> must exit the loop without injecting 'continue'."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _make_response(
            f"Please tell me your name. {AWAIT_USER_FLAG}"
        )

        result = loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 1
        assert AWAIT_USER_FLAG not in result
        assert "Please tell me your name." in result

    def test_wait_flag_stripped_from_result(self):
        """Flag must be stripped before the result is returned."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _make_response(
            f"What is your goal? {AWAIT_USER_FLAG}"
        )

        result = loop.run("do something")

        assert AWAIT_USER_FLAG not in result

    def test_wait_flag_fires_on_done_callback(self):
        """on_done must fire when the wait flag exits the loop."""
        done_results = []
        callbacks = AgentCallbacks(on_done=lambda r: done_results.append(r))

        loop = _make_loop()
        loop.client = MagicMock()
        loop.callbacks = callbacks
        loop.client.chat.completions.create.return_value = _make_response(
            f"Awaiting your input. {AWAIT_USER_FLAG}"
        )

        loop.run("do something")

        assert len(done_results) == 1
        assert AWAIT_USER_FLAG not in done_results[0]

    def test_wait_flag_does_not_inject_continue(self):
        """No 'continue' user message must appear in history after wait flag."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _make_response(
            f"Your move. {AWAIT_USER_FLAG}"
        )

        loop.run("do something")

        from agent.loop import CONTINUE_PROMPT
        continue_msgs = [m for m in loop._messages if m.get("content") == CONTINUE_PROMPT]
        assert len(continue_msgs) == 0


class TestApiErrorRetryConfig:
    def test_default_api_error_retries(self):
        """AgentConfig defaults api_error_retries to 3."""
        config = AgentConfig(
            model="test-model",
            api_key="test-key",
            system_prompt="You are a test agent.",
        )
        assert config.api_error_retries == 3


def _make_api_status_error(status_code: int, message: str = "Server Error"):
    """Build a fake openai.APIStatusError with the given status code."""
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return openai.APIStatusError(
        message=message, response=response, body=None,
    )


class TestApiErrorRetry:
    def test_transient_error_retries_then_succeeds(self):
        """A single 500 followed by a valid response should succeed."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_api_status_error(500),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep"):
            result = loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 2
        assert "Done." in result

    def test_non_transient_error_raises_immediately(self):
        """A 401 should not be retried — raises immediately."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = _make_api_status_error(401)

        with pytest.raises(openai.APIStatusError) as exc_info:
            loop.run("do something")
        assert exc_info.value.status_code == 401
        assert loop.client.chat.completions.create.call_count == 1

    def test_exhausted_retries_raises(self):
        """After api_error_retries failures, the exception propagates."""
        loop = _make_loop()
        loop.config.api_error_retries = 2
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = _make_api_status_error(503)

        with patch("agent.loop.time.sleep"):
            with pytest.raises(openai.APIStatusError):
                loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 2

    def test_429_is_retried(self):
        """Rate limit (429) is treated as transient."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_api_status_error(429, "Rate limited"),
            _make_response(f"OK. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep"):
            result = loop.run("do something")

        assert "OK." in result

    def test_connection_error_is_retried(self):
        """APIConnectionError is treated as transient."""
        loop = _make_loop()
        loop.client = MagicMock()
        request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
        loop.client.chat.completions.create.side_effect = [
            openai.APIConnectionError(request=request),
            _make_response(f"OK. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep"):
            result = loop.run("do something")

        assert "OK." in result

    def test_retry_counter_resets_per_iteration(self):
        """Each loop iteration gets a fresh retry budget."""
        loop = _make_loop(max_continuations=1)
        loop.config.api_error_retries = 2
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_api_status_error(500),
            _make_response("Still working..."),
            _make_api_status_error(502),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep"):
            result = loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 4
        assert "Done." in result

    def test_backoff_delay_increases(self):
        """Backoff should use 2^attempt seconds, capped at 60."""
        loop = _make_loop()
        loop.config.api_error_retries = 4
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_api_status_error(500),
            _make_api_status_error(500),
            _make_api_status_error(500),
            _make_response(f"OK. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep") as mock_sleep:
            loop.run("do something")

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [2, 4, 8]

    def test_on_assistant_text_called_during_retry(self):
        """User should see a retry notification."""
        texts = []
        callbacks = AgentCallbacks(on_assistant_text=lambda t: texts.append(t))

        loop = _make_loop()
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_api_status_error(500, "Internal Server Error"),
            _make_response(f"OK. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep"):
            loop.run("do something")

        retry_msgs = [t for t in texts if "Retrying" in t]
        assert len(retry_msgs) == 1
        assert "1/3" in retry_msgs[0]
