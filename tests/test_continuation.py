"""tests/test_continuation.py — Unit tests for loop termination and continuation."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from agent.loop import AgentConfig, AgentCallbacks, AgentLoop
from agent.protocol import SideEffect, ToolResult
from agent._loop_config import CompactionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_handoff_tc(content: str = "done"):
    """A fake OpenAI tool call for write_handoff."""
    return SimpleNamespace(
        id="tc_handoff",
        function=SimpleNamespace(
            name="write_handoff",
            arguments=json.dumps({"content": content}),
        ),
    )


def _make_response(content: str, tool_calls=None):
    """Build a minimal fake OpenAI chat completion response."""
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        cost=None,
        completion_tokens_details=None,
        prompt_tokens_details=None,
    )
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls or [],
        model_extra={},
        reasoning_content=None,
    )
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


def _exit_response(content: str = "done"):
    """Response where the model calls write_handoff to end the turn."""
    return _make_response(content="", tool_calls=[_write_handoff_tc(content)])


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
    fake_registry._tools = {"write_handoff": SimpleNamespace(description="submit handoff")}

    def _dispatch(name, args):
        if name == "write_handoff":
            return ToolResult(
                output=args.get("content", ""),
                side_effect=SideEffect.END_TURN,
            )
        return f"result of {name}"

    fake_registry.dispatch.side_effect = _dispatch

    fake_tracker = MagicMock()
    fake_tracker.record_system = MagicMock()
    fake_tracker.record_user = MagicMock()
    fake_tracker.record_assistant = MagicMock()
    fake_tracker.thread_id = "test"

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
    loop._skip_slug_generation = True
    return loop


# ---------------------------------------------------------------------------
# Tests: write_handoff as exit mechanism
# ---------------------------------------------------------------------------

class TestWriteHandoffExit:
    def test_write_handoff_exits_loop(self):
        """write_handoff tool call exits the loop and returns content."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _exit_response("All done!")

        result = loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 1
        assert "All done!" in result

    def test_write_handoff_fires_on_done_callback(self):
        """on_done callback must fire when write_handoff ends the turn."""
        done_results = []
        callbacks = AgentCallbacks(on_done=lambda r: done_results.append(r))

        loop = _make_loop()
        loop.client = MagicMock()
        loop.callbacks = callbacks
        loop.client.chat.completions.create.return_value = _exit_response("Task complete.")

        loop.run("do something")

        assert len(done_results) == 1
        assert "Task complete." in done_results[0]

    def test_write_handoff_does_not_inject_continue(self):
        """No 'continue' user message must appear after write_handoff call."""
        from agent.loop import CONTINUE_PROMPT
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _exit_response("Done.")

        loop.run("do something")

        continue_msgs = [m for m in loop._messages if m.get("content") == CONTINUE_PROMPT]
        assert len(continue_msgs) == 0


class TestContinuationMechanism:
    def test_no_tool_calls_injects_continue(self):
        """Without write_handoff, the harness should inject 'continue' and loop."""
        loop = _make_loop(max_continuations=1)
        loop.client = MagicMock()

        # First call: no tool calls → triggers continuation
        # Second call: write_handoff → clean return
        loop.client.chat.completions.create.side_effect = [
            _make_response("Still working..."),
            _exit_response("Finished."),
        ]

        result = loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 2
        assert "Finished." in result

    def test_continue_message_appended_to_history(self):
        """A continuation user message must appear in _messages after an incomplete response."""
        from agent.loop import CONTINUE_PROMPT
        loop = _make_loop(max_continuations=1)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response("Still working..."),
            _exit_response("Done."),
        ]

        loop.run("do something")

        roles = [m["role"] for m in loop._messages]
        assert "user" in roles
        continue_msgs = [m for m in loop._messages if m.get("content") == CONTINUE_PROMPT]
        assert len(continue_msgs) == 1

    def test_safety_valve_exits_at_max_continuations(self):
        """After max_continuations injections, the loop must exit without write_handoff."""
        max_cont = 2
        loop = _make_loop(max_continuations=max_cont)
        loop.client = MagicMock()

        # Always return without tool calls
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
            _exit_response("Done."),
        ]

        loop.run("do something")

        assert loop._continuation_count == 2

    def test_on_done_fires_after_max_continuations(self):
        """on_done must fire even when loop exits via max_continuations."""
        done_results = []
        callbacks = AgentCallbacks(on_done=lambda r: done_results.append(r))

        loop = _make_loop(max_continuations=1)
        loop.client = MagicMock()
        loop.callbacks = callbacks
        loop.client.chat.completions.create.return_value = _make_response("Still working.")

        loop.run("do something")

        assert len(done_results) == 1


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
            _exit_response("Done."),
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
            _exit_response("OK."),
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
            _exit_response("OK."),
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
            _exit_response("Done."),
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
            _exit_response("OK."),
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
            _exit_response("OK."),
        ]

        with patch("agent.loop.time.sleep"):
            loop.run("do something")

        retry_msgs = [t for t in texts if "Retrying" in t]
        assert len(retry_msgs) == 1
        assert "1/3" in retry_msgs[0]


class TestErrorPause:
    def test_error_pause_blocks_instead_of_raising(self):
        """With supports_pause=True, exhausted transient retries pause the loop, not raise."""
        paused: list = []
        callbacks = AgentCallbacks(
            on_pause=lambda: paused.append(True),
            supports_pause=True,
        )

        loop = _make_loop()
        loop.config.api_error_retries = 1
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = _make_api_status_error(503)

        t = threading.Thread(target=loop.run, args=("do something",), daemon=True)
        with patch("agent.loop.time.sleep"):
            t.start()
            t.join(timeout=1.0)  # should NOT finish — loop is blocked on _pause_event

        assert t.is_alive(), "loop should be paused (blocking), not returned or raised"
        assert not loop._pause_event.is_set(), "_pause_event should be cleared (paused state)"
        assert paused, "on_pause callback should have fired"

    def test_error_pause_resumes_with_inject_and_resume(self):
        """inject_and_resume after an error-pause unblocks the loop with full context."""
        paused: list = []
        callbacks = AgentCallbacks(
            on_pause=lambda: paused.append(True),
            supports_pause=True,
        )

        loop = _make_loop()
        loop.config.api_error_retries = 1
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_api_status_error(503),
            _exit_response("Recovered."),
        ]

        result_holder: list = []

        def _run():
            result_holder.append(loop.run("do something"))

        t = threading.Thread(target=_run, daemon=True)
        with patch("agent.loop.time.sleep"):
            t.start()
            deadline = time.time() + 2.0
            while time.time() < deadline and not paused:
                time.sleep(0.01)

        assert paused, "loop should have paused before resume"
        loop.inject_and_resume("please retry")
        t.join(timeout=2.0)

        assert not t.is_alive(), "loop should have finished after resume"
        assert result_holder and "Recovered." in result_holder[0]
        assert any(
            m.get("content") == "please retry" for m in loop._messages
        ), "injected message must appear in _messages"


class TestCompactionStartedCallback:
    def test_compaction_started_callback_exists(self):
        """AgentCallbacks must have an on_compaction_started field."""
        callbacks = AgentCallbacks()
        assert callable(callbacks.on_compaction_started)


class TestCompactionStartedFired:
    def test_compaction_started_fires_before_compact(self):
        """on_compaction_started must fire before compact() is called."""
        call_order = []
        callbacks = AgentCallbacks(
            on_compaction_started=lambda: call_order.append("started"),
        )

        loop = _make_loop()
        loop.callbacks = callbacks
        loop.compact = MagicMock(
            side_effect=lambda **kw: call_order.append("compact") or CompactionResult(
                did_compact=True, generation=1, summary_content="summary", removed_count=5,
            ),
        )

        loop._compact_context()

        assert call_order == ["started", "compact"]


class TestFullCompaction:
    def test_compact_summarize_all_puts_everything_in_middle(self):
        """compact(summarize_all=True) must summarize all steps, keeping none as tail."""
        loop = _make_loop()
        loop.client = MagicMock()

        # Run a task that produces multiple steps with continue prompts
        loop.client.chat.completions.create.side_effect = [
            _make_response("step 1"),
            _make_response("step 2"),
            _make_response("step 3"),
            _exit_response("Done."),
        ]
        loop.run("do something")

        # Now attempt full compaction — mock the subagent to return a summary.
        # compact() appends surface events that require an open turn.
        from agent import session_events as sev
        _turn = loop.log.next_turn()
        loop.log.append(sev.TURN_START, {"turn": _turn})

        with patch("agent._compaction.run_subagent") as mock_sub:
            mock_sub.return_value = SimpleNamespace(
                is_ok=True, handoff_text="Full summary of conversation.",
                handoff_path="/tmp/fake",
            )
            result = loop.compact(summarize_all=True)

        assert result.did_compact
        # After full compaction, the surface should have only the compaction
        # summary node — no retained tail steps
        msgs = loop.log.derive_messages()
        assert len(msgs) == 1
        assert "Full summary" in msgs[0]["content"]


class TestGarbledLoopRecovery:
    def test_garbled_loop_triggers_full_compaction(self):
        """Consecutive empty-content responses must trigger revise + full compaction."""
        compaction_started = []
        callbacks = AgentCallbacks(
            on_compaction_started=lambda: compaction_started.append(True),
        )

        loop = _make_loop(max_continuations=10)
        loop.callbacks = callbacks
        loop.client = MagicMock()

        # 3 empty responses (garbled), then after compaction the model recovers
        loop.client.chat.completions.create.side_effect = [
            _make_response(""),  # garbled 1
            _make_response(""),  # garbled 2
            _make_response(""),  # garbled 3 → triggers recovery
            _exit_response("Recovered after compaction."),
        ]

        with patch.object(loop, "compact") as mock_compact:
            mock_compact.return_value = CompactionResult(
                did_compact=True, generation=1,
                summary_content="[CONTEXT SUMMARY]\nsummary", removed_count=3,
            )
            result = loop.run("do something")

        mock_compact.assert_called_once_with(summarize_all=True)
        assert compaction_started, "on_compaction_started should have fired"

    def test_non_empty_response_resets_garbled_counter(self):
        """A response with content must reset the empty-content counter."""
        loop = _make_loop(max_continuations=10)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(""),      # garbled 1
            _make_response(""),      # garbled 2
            _make_response("real"),  # resets counter
            _make_response(""),      # garbled 1 again
            _make_response(""),      # garbled 2
            _exit_response("Done."),
        ]

        with patch.object(loop, "compact") as mock_compact:
            result = loop.run("do something")

        # Should NOT have triggered compaction — never hit 3 consecutive
        mock_compact.assert_not_called()
        assert "Done." in result

    def test_garbled_recovery_removes_empty_steps(self):
        """After recovery, the empty garbled steps must not be on the surface."""
        loop = _make_loop(max_continuations=10)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(""),  # garbled 1
            _make_response(""),  # garbled 2
            _make_response(""),  # garbled 3 → triggers recovery
            _exit_response("Recovered."),
        ]

        with patch.object(loop, "compact") as mock_compact:
            mock_compact.return_value = CompactionResult(
                did_compact=True, generation=1,
                summary_content="[CONTEXT SUMMARY]\nsummary", removed_count=3,
            )
            loop.run("do something")

        # The empty assistant messages should have been revised away
        # (exclude tool-call messages like write_handoff which legitimately have empty content)
        empty_assistant_msgs = [
            m for m in loop._messages
            if m.get("role") == "assistant"
            and not (m.get("content") or "").strip()
            and not m.get("tool_calls")
        ]
        assert len(empty_assistant_msgs) == 0
