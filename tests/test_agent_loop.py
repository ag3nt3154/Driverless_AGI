"""tests/test_agent_loop.py — Unit tests for AgentLoop tool dispatch and compaction trigger."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent import session_events as sev
from agent.base_tool import BaseTool
from agent.loop import (
    AgentCallbacks, AgentConfig, AgentLoop,
    AWAIT_USER_FLAG, TASK_END_FLAG, WRITE_HANDOFF_SENTINEL,
    _escape_sentinels,
)
from agent.affect import AffectConfig, AffectController, AffectRestore, AffectVector
from agent.expression_assets import ImageAsset
from agent.registry import ToolRegistry


class FakeTool(BaseTool):
    def __init__(self, name="echo", description="Echoes input", result="tool ran"):
        self.name = name
        self.description = description
        self._parameters = {"type": "object", "properties": {}, "required": []}
        self._result = result
        self.calls: list[dict] = []

    def run(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self._result


def _make_response(content, tool_calls=None, prompt_tokens=10, completion_tokens=5):
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost=None,
        completion_tokens_details=None,
    )
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [], model_extra={})
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_tool_call(call_id, name, arguments="{}"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def _make_loop(registry=None, **config_overrides) -> AgentLoop:
    config = AgentConfig(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        **config_overrides,
    )

    real_registry = registry or ToolRegistry()

    fake_tracker = MagicMock()
    fake_tracker.affect_controller = None

    with (
        patch("agent.loop.SessionTracker", return_value=fake_tracker),
        patch("openai.OpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        loop = AgentLoop(config=config, _registry=real_registry, _tracker=fake_tracker)

    loop.tracker = fake_tracker
    loop.registry = real_registry
    # Suppress slug-generation side-call so existing tests don't need an extra
    # mocked response at the front of their side_effect list.
    loop._skip_slug_generation = True
    return loop


class _PauseAfterIsSet:
    """Event double that requests pause immediately after a running check.

    Old check-then-act code lets the pause finish before the transition/drift
    publishes. A locked implementation makes the pause wait until that side
    effect completes, preserving a serializable order.
    """

    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop
        self._event = threading.Event()
        self._event.set()
        self._armed = True
        self.pause_finished = threading.Event()

    def is_set(self) -> bool:
        running = self._event.is_set()
        if running and self._armed:
            self._armed = False
            thread = threading.Thread(target=self._pause_loop)
            thread.start()
            self.pause_finished.wait(timeout=0.05)
        return running

    def set(self) -> None:
        self._event.set()

    def clear(self) -> None:
        self._event.clear()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def _pause_loop(self) -> None:
        self._loop.pause()
        self.pause_finished.set()


class _ExitBarrierLock:
    """RLock wrapper that can pause one owner just after releasing a with-block."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._armed_thread: int | None = None
        self.entered = threading.Event()
        self.release = threading.Event()

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, exc_type, exc, tb) -> bool:
        should_block = self._armed_thread == threading.get_ident()
        self._armed_thread = None
        result = self._lock.__exit__(exc_type, exc, tb)
        if should_block:
            self.entered.set()
            self.release.wait(timeout=2.0)
        return result

    def arm_current_exit(self) -> None:
        self._armed_thread = threading.get_ident()


class TestToolDispatch:
    def test_tool_call_dispatches_to_registered_tool(self):
        tool = FakeTool(name="echo", result="echoed!")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "echo", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("do something")

        assert tool.calls == [{}]

    def test_tool_result_appended_to_message_history(self):
        tool = FakeTool(name="echo", result="echoed!")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "echo", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("do something")

        tool_msgs = [m for m in loop._messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tc1"
        assert tool_msgs[0]["content"] == "echoed!"

    def test_on_tool_start_and_on_tool_end_callbacks_fire(self):
        tool = FakeTool(name="echo", result="echoed!")
        registry = ToolRegistry()
        registry.register(tool)

        starts = []
        ends = []
        callbacks = AgentCallbacks(
            on_tool_start=lambda name, desc, args: starts.append((name, desc, args)),
            on_tool_end=lambda name, result: ends.append((name, result)),
        )

        loop = _make_loop(registry=registry)
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "echo", '{"x": 1}')]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("do something")

        assert starts == [("echo", "Echoes input", '{"x": 1}')]
        assert ends == [("echo", "echoed!")]

    def test_tracker_records_tool_start_and_end(self):
        tool = FakeTool(name="echo", result="echoed!")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "echo", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("do something")

        loop.tracker.record_tool_start.assert_called_once_with("echo", "Echoes input", "{}")
        loop.tracker.record_tool_end.assert_called_once_with("echo", "echoed!")

    def test_unknown_tool_call_yields_error_result_and_loop_continues(self):
        registry = ToolRegistry()
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "nonexistent", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("do something")

        tool_msgs = [m for m in loop._messages if m.get("role") == "tool"]
        assert tool_msgs[0]["content"] == "Error: unknown tool 'nonexistent'"

    def test_multiple_tool_calls_in_one_response_all_dispatch(self):
        tool_a = FakeTool(name="tool_a", result="result a")
        tool_b = FakeTool(name="tool_b", result="result b")
        registry = ToolRegistry()
        registry.register(tool_a)
        registry.register(tool_b)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(
                "Using two tools",
                tool_calls=[
                    _make_tool_call("tc1", "tool_a", "{}"),
                    _make_tool_call("tc2", "tool_b", "{}"),
                ],
            ),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("do something")

        assert tool_a.calls == [{}]
        assert tool_b.calls == [{}]
        tool_msgs = [m for m in loop._messages if m.get("role") == "tool"]
        assert [m["tool_call_id"] for m in tool_msgs] == ["tc1", "tc2"]


class TestWriteHandoffSentinel:
    """WRITE_HANDOFF_SENTINEL in a tool result must terminate the subagent's
    turn immediately — no further API calls, transcript stays well-formed."""

    def test_run_returns_cleaned_text_and_makes_no_further_api_call(self):
        tool = FakeTool(name="write_handoff", result=f"Handoff written. {WRITE_HANDOFF_SENTINEL}")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "write_handoff", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        result = loop.run("do something")

        assert result == "Handoff written."
        assert loop.client.chat.completions.create.call_count == 1

    def test_returned_text_does_not_contain_raw_sentinel(self):
        tool = FakeTool(name="write_handoff", result=f"Handoff written. {WRITE_HANDOFF_SENTINEL}")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "write_handoff", "{}")]),
        ]

        result = loop.run("do something")

        assert WRITE_HANDOFF_SENTINEL not in result

    def test_transcript_has_well_formed_tool_reply(self):
        tool = FakeTool(name="write_handoff", result=f"Handoff written. {WRITE_HANDOFF_SENTINEL}")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "write_handoff", "{}")]),
        ]

        loop.run("do something")

        tool_msgs = [m for m in loop._messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tc1"
        assert tool_msgs[0]["content"] == "Handoff written."

    def test_on_done_callback_fires_with_cleaned_text(self):
        tool = FakeTool(name="write_handoff", result=f"Handoff written. {WRITE_HANDOFF_SENTINEL}")
        registry = ToolRegistry()
        registry.register(tool)

        done_calls = []
        callbacks = AgentCallbacks(on_done=lambda r: done_calls.append(r))

        loop = _make_loop(registry=registry)
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "write_handoff", "{}")]),
        ]

        loop.run("do something")

        assert done_calls == ["Handoff written."]

    def test_bookkeeping_fires_on_handoff_path(self):
        """record_assistant and on_token_update must fire on the handoff
        termination path, same as every other early-exit path."""
        tool = FakeTool(name="write_handoff", result=f"Handoff written. {WRITE_HANDOFF_SENTINEL}")
        registry = ToolRegistry()
        registry.register(tool)

        token_updates = []
        callbacks = AgentCallbacks(
            on_token_update=lambda p, c, cost, t, cached=0: token_updates.append((p, c, cost, t))
        )

        loop = _make_loop(registry=registry)
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(
                None,
                tool_calls=[_make_tool_call("tc1", "write_handoff", "{}")],
                prompt_tokens=10,
                completion_tokens=5,
            ),
        ]

        loop.run("do something")

        loop.tracker.record_assistant.assert_called_once()
        assert token_updates == [(10, 5, None, 0)]

    def test_large_handoff_result_gets_filtered(self, tmp_path):
        """A large handoff report must be routed through filter_tool_output,
        same as the normal per-tool-call path."""
        large_report = "x" * 100_000
        tool = FakeTool(
            name="write_handoff", result=f"{large_report}{WRITE_HANDOFF_SENTINEL}"
        )
        registry = ToolRegistry()
        registry.register(tool)

        warnings = []
        done_calls = []
        handoff_calls = []
        callbacks = AgentCallbacks(
            on_assistant_text=lambda t: warnings.append(t),
            on_done=lambda result: done_calls.append(result),
            on_handoff=lambda: handoff_calls.append(True),
        )

        loop = _make_loop(registry=registry, reserve_tokens=10, project_path=tmp_path)
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "write_handoff", "{}")]),
        ]

        result = loop.run("do something")

        tool_msgs = [m for m in loop._messages if m.get("role") == "tool"]
        assert "OUTPUT TRUNCATED" in tool_msgs[0]["content"]
        assert any("[output filter]" in w for w in warnings)
        # Final returned/on_done value is the full, unfiltered report (JSONL/caller-facing).
        assert result == large_report
        assert done_calls == [large_report]
        assert handoff_calls == [True]

    def test_non_write_handoff_tool_containing_sentinel_does_not_short_circuit(self):
        """A tool other than write_handoff (e.g. a subagent spawn tool inlining a handoff
        file that contains <<HANDOFF_WRITTEN>>) must NOT trigger _handle_write_handoff."""
        tool = FakeTool(
            name="spawn_subagent",
            result=f"Subagent done.\n--- Handoff ---\n{WRITE_HANDOFF_SENTINEL}\nreport text",
        )
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "spawn_subagent", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        result = loop.run("spawn a subagent")

        # Must have continued to the second LLM call — no false short-circuit.
        assert loop.client.chat.completions.create.call_count == 2
        assert result == "Done."

    def test_non_sentinel_tool_result_behaves_as_before(self):
        """Regression guard: a normal tool result without the sentinel proceeds
        to the next iteration rather than returning early."""
        tool = FakeTool(name="echo", result="just a normal result")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "echo", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        result = loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 2
        assert result == "Done."


class TestCompactionTrigger:
    """The token-budget compaction check only runs after a tool-calling turn
    (see agent/loop.py's run loop — a no-tool-call turn that hits an exit
    flag returns before the compaction check), so these tests route through
    one tool call before finishing."""

    def test_compaction_fires_when_prompt_tokens_exceed_budget(self):
        from unittest.mock import patch
        tool = FakeTool(name="echo")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry, context_window=1000, reserve_tokens=100)
        loop.client = MagicMock()
        # prompt_tokens (950) > context_window - reserve_tokens (900) -> should trigger compaction
        loop.client.chat.completions.create.side_effect = [
            _make_response(
                None, tool_calls=[_make_tool_call("tc1", "echo", "{}")], prompt_tokens=950
            ),
            _make_response(f"Done. {TASK_END_FLAG}", prompt_tokens=50),
        ]

        from agent.loop import _NO_COMPACTION
        with patch.object(loop, "compact", return_value=_NO_COMPACTION) as mock_compact:
            loop.run("do something")
            mock_compact.assert_called_once()

    def test_compaction_does_not_fire_below_budget(self):
        from unittest.mock import patch
        tool = FakeTool(name="echo")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry, context_window=1000, reserve_tokens=100)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(
                None, tool_calls=[_make_tool_call("tc1", "echo", "{}")], prompt_tokens=50
            ),
            _make_response(f"Done. {TASK_END_FLAG}", prompt_tokens=50),
        ]

        from agent.loop import _NO_COMPACTION
        with patch.object(loop, "compact", return_value=_NO_COMPACTION) as mock_compact:
            loop.run("do something")
            mock_compact.assert_not_called()

    def test_compaction_disabled_when_context_window_is_zero(self):
        from unittest.mock import patch
        tool = FakeTool(name="echo")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry, context_window=0, reserve_tokens=100)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(
                None, tool_calls=[_make_tool_call("tc1", "echo", "{}")], prompt_tokens=999_999
            ),
            _make_response(f"Done. {TASK_END_FLAG}", prompt_tokens=50),
        ]

        from agent.loop import _NO_COMPACTION
        with patch.object(loop, "compact", return_value=_NO_COMPACTION) as mock_compact:
            loop.run("do something")
            mock_compact.assert_not_called()

    def test_compact_context_swallows_errors_and_warns(self):
        from unittest.mock import patch
        loop = _make_loop()
        warnings = []
        loop.callbacks = AgentCallbacks(on_assistant_text=lambda t: warnings.append(t))

        with patch.object(loop, "compact", side_effect=RuntimeError("compaction blew up")):
            result = loop._compact_context()

        assert result.did_compact is False
        assert any("compaction blew up" in w for w in warnings)


class TestSentinelEscape:
    """Sentinel strings in tool results must not leak into message history and
    cause premature loop termination on the next LLM turn."""

    def test_escape_sentinels_breaks_await_flag(self):
        escaped = _escape_sentinels(f"prefix {AWAIT_USER_FLAG} suffix")
        assert AWAIT_USER_FLAG not in escaped
        assert "END_OF_RESPONSE" in escaped  # content still visible, just broken

    def test_escape_sentinels_breaks_task_end_flag(self):
        escaped = _escape_sentinels(f"prefix {TASK_END_FLAG} suffix")
        assert TASK_END_FLAG not in escaped
        assert "TASK_END" in escaped

    def test_escape_sentinels_is_idempotent_on_clean_text(self):
        text = "no sentinels here"
        assert _escape_sentinels(text) == text

    def test_tool_result_containing_sentinel_does_not_terminate_loop(self):
        """A tool that returns <<END_OF_RESPONSE>> verbatim (e.g. ReadTool reading a
        session log) must not break the parent loop — the loop should continue and
        reach the explicit exit flag on the next turn."""
        tool = FakeTool(name="read", result=f"file content\n{AWAIT_USER_FLAG}\nmore text")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "read", "{}")]),
            _make_response(f"All done. {TASK_END_FLAG}"),
        ]

        result = loop.run("read a file")

        # Must have made TWO LLM calls — tool call turn + final text turn.
        assert loop.client.chat.completions.create.call_count == 2
        assert result == "All done."
        # Sentinel must be escaped in the tool message stored in history.
        tool_msgs = [m for m in loop._messages if m.get("role") == "tool"]
        assert AWAIT_USER_FLAG not in tool_msgs[0]["content"]

    def test_on_tool_end_callback_receives_unescaped_result(self):
        """The UI callback gets the original unescaped string — only the LLM message
        history is sanitised."""
        tool = FakeTool(name="read", result=f"data {AWAIT_USER_FLAG} end")
        registry = ToolRegistry()
        registry.register(tool)

        ends = []
        callbacks = AgentCallbacks(on_tool_end=lambda name, result: ends.append(result))
        loop = _make_loop(registry=registry)
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "read", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("read a file")

        # on_tool_end receives the filtered (but not sentinel-escaped) string.
        assert AWAIT_USER_FLAG in ends[0]


class TestSystemPromptRefresh:
    """When a new AgentLoop is constructed with initial_messages (multi-turn
    continuation), the system message must reflect the freshly-assembled prompt
    rather than the stale one carried over from the previous loop."""

    def test_system_prompt_refreshed_when_initial_messages_provided(self):
        """_messages[0] must contain the NEW system prompt, not the old one."""
        config = AgentConfig(
            model="test-model",
            api_key="test-key",
            system_prompt="Original prompt.",
        )
        fake_tracker = MagicMock()

        with (
            patch("agent.loop.SessionTracker", return_value=fake_tracker),
            patch("openai.OpenAI"),
            patch.object(Path, "exists", return_value=False),
        ):
            first_loop = AgentLoop(config=config, _tracker=fake_tracker)

        stale_system = first_loop._messages[0]
        old_messages = list(first_loop._messages)

        # Now create a second loop with updated system prompt, passing the old messages.
        updated_config = AgentConfig(
            model="test-model",
            api_key="test-key",
            system_prompt="Updated prompt after AGENTS.md change.",
        )
        with (
            patch("agent.loop.SessionTracker", return_value=fake_tracker),
            patch("openai.OpenAI"),
            patch.object(Path, "exists", return_value=False),
        ):
            second_loop = AgentLoop(
                config=updated_config,
                _tracker=fake_tracker,
                initial_messages=old_messages,
            )

        assert second_loop._messages[0]["content"] != stale_system["content"]
        assert "Updated prompt" in second_loop._messages[0]["content"]


class TestDispatchToolCallsExtraction:
    """_dispatch_tool_calls owns the per-tool-call loop extracted from run().

    The method emits tool/call and tool/result events, which the session log
    requires to be turn-enclosed. In production it is only ever reached from
    inside run()'s try block, where a turn is always open; calling it
    directly has to supply that context itself, hence `_open_turn` below.
    """

    @staticmethod
    def _open_turn(loop) -> None:
        loop.log.append(sev.TURN_START, {"turn": 1})
        loop.log.append(sev.STEP_START, {"turn": 1, "step": 1})

    def test_returns_none_when_no_sentinel_fires(self):
        loop = _make_loop()
        self._open_turn(loop)
        loop._messages = [{"role": "system", "content": "sys"}]
        tc = _make_tool_call("call_1", "read", '{"file_path": "a.txt"}')
        message = SimpleNamespace(tool_calls=[tc], content=None)
        response = _make_response(None, tool_calls=[tc])
        loop.registry.dispatch = MagicMock(return_value="file contents")
        loop.registry._tools = {}

        result = loop._dispatch_tool_calls(message, response, [])

        assert result is None
        assert loop._messages[-1]["role"] == "tool"
        assert loop._messages[-1]["tool_call_id"] == "call_1"

    def test_deferred_system_messages_land_after_all_tool_results(self):
        from agent.loop import RELOAD_SKILLS_SENTINEL

        loop = _make_loop()
        loop._messages = [{"role": "system", "content": "sys"}]
        tc_a = _make_tool_call("call_a", "reload_skills")
        tc_b = _make_tool_call("call_b", "read", '{"file_path": "a"}')
        message = SimpleNamespace(tool_calls=[tc_a, tc_b], content=None)
        response = _make_response(None, tool_calls=[tc_a, tc_b])
        loop.registry._tools = {}
        loop.registry.dispatch = MagicMock(side_effect=[RELOAD_SKILLS_SENTINEL, "ok"])
        loop._rebuild_for_reload = MagicMock(return_value=(set(), set(), []))
        self._open_turn(loop)

        loop._dispatch_tool_calls(message, response, [])

        roles = [m["role"] for m in loop._messages]
        # Both tool results precede the deferred system notification.
        assert roles.index("system", 1) > roles.index("tool")
        assert roles[-1] == "system"

    def test_write_handoff_sentinel_short_circuits_with_a_string(self):
        loop = _make_loop()
        self._open_turn(loop)
        loop._messages = [{"role": "system", "content": "sys"}]
        tc = _make_tool_call("call_h", "write_handoff", "{}")
        message = SimpleNamespace(tool_calls=[tc], content=None)
        response = _make_response(None, tool_calls=[tc])
        loop.registry._tools = {}
        loop.registry.dispatch = MagicMock(
            return_value=f"{WRITE_HANDOFF_SENTINEL}handoff body"
        )

        result = loop._dispatch_tool_calls(message, response, [])

        assert result == "handoff body"


class TestSessionLogWiring:
    """AgentLoop passes its session log to the tool registry."""

    def test_subagent_tools_receive_session_log(self, tmp_path):
        """Subagent tools discovered during AgentLoop init receive the log."""
        from unittest.mock import patch

        config = AgentConfig(
            api_key="test-key",
            project_path=tmp_path,
        )

        captured_kwargs: dict = {}

        def spy_discover(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return []

        with patch("agent.tools._discover_subagent_tools", side_effect=spy_discover):
            loop = AgentLoop(config=config)

        assert "session_log" in captured_kwargs
        assert captured_kwargs["session_log"] is loop.log

    def test_main_loop_binds_affect_controller_before_registry_build(self, tmp_path):
        """A normal main loop must expose adjust_affect when config allowlists it."""
        from agent.affect import AffectController

        config = AgentConfig(
            api_key="test-key",
            project_path=tmp_path,
            system_prompt="{tools_and_skills}",
            tools=["adjust_affect"],
        )

        with patch("openai.OpenAI"):
            loop = AgentLoop(config=config)

        names = {name for name, _description in loop.registry.list_tools()}
        assert isinstance(loop.tracker.affect_controller, AffectController)
        assert "adjust_affect" in names
        assert "emote" not in names

    def test_initial_affect_restore_reuses_state_without_init_record(self, tmp_path):
        """Restoring history must carry affect forward without inventing a new baseline."""
        seen = []
        restore = AffectRestore(
            baseline=AffectVector(0.1, -0.2, 0.3),
            current=AffectVector(0.2, -0.1, 0.4),
            emote_id="steady",
        )
        callbacks = AgentCallbacks(on_affect_changed=seen.append)
        config = AgentConfig(
            api_key="test-key",
            project_path=tmp_path,
            system_prompt="{tools_and_skills}",
        )

        with patch("openai.OpenAI"):
            loop = AgentLoop(config=config, callbacks=callbacks, initial_affect=restore)

        affect_records = [
            json.loads(line)
            for line in loop.tracker._path.read_text(encoding="utf-8").splitlines()
            if json.loads(line).get("type", "").startswith("affect_")
        ]
        assert [record["type"] for record in affect_records] == []
        assert loop.tracker.affect_controller.baseline == restore.baseline
        assert loop.tracker.affect_controller.current == restore.current
        assert seen[-1].current == restore.current


class TestProcessLifecycle:
    def test_reload_short_circuit_marks_process_idle_before_notification(self):
        """A successful /reload is a completed turn and must not leave the UI paused."""
        events: list[str] = []
        callbacks = AgentCallbacks(
            on_process_state_changed=lambda snap: events.append(f"process:{snap.state}"),
            on_assistant_text=lambda _text: events.append("assistant_text"),
        )
        loop = _make_loop()
        loop.callbacks = callbacks
        loop._process.set_listener(loop.callbacks.on_process_state_changed)
        loop.pause()
        loop._rebuild_for_reload = MagicMock(return_value=(set(), set(), []))

        loop.run("/reload")

        assert events == ["process:idle", "process:paused", "process:idle", "assistant_text"]

    def test_process_state_wraps_api_attempt_tool_call_and_completion(self):
        """Process callbacks must bracket the real lifecycle, not lag behind UI callbacks."""
        tool = FakeTool(name="echo", result="echoed!")
        registry = ToolRegistry()
        registry.register(tool)
        events: list[str] = []
        callbacks = AgentCallbacks(
            on_process_state_changed=lambda snap: events.append(f"process:{snap.state}"),
            on_api_call=lambda _messages: events.append("api"),
            on_tool_start=lambda name, _desc, _args: events.append(f"tool_start:{name}"),
            on_tool_end=lambda name, _result: events.append(f"tool_end:{name}"),
            on_done=lambda _result: events.append("done"),
        )
        loop = _make_loop(registry=registry)
        loop.callbacks = callbacks
        loop._process.set_listener(loop.callbacks.on_process_state_changed)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "echo", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("do something")

        assert events.index("process:thinking") < events.index("api")
        assert events.index("process:tool:echo") < events.index("tool_start:echo")
        assert events.index("tool_end:echo") < events.index("process:thinking", 3)
        assert events[-2:] == ["process:idle", "done"]

    def test_affect_drifts_after_step_end_only_when_loop_continues(self, tmp_path):
        """Affect drift belongs after a completed continuing step, never on final return."""
        tool = FakeTool(name="echo", result="echoed!")
        registry = ToolRegistry()
        registry.register(tool)
        config = AgentConfig(
            model="test-model",
            api_key="test-key",
            system_prompt="You are a test agent.",
            project_path=tmp_path,
            affect_drift_pull=0.0,
            affect_drift_noise=0.0,
        )
        with (
            patch("openai.OpenAI"),
            patch.object(Path, "exists", return_value=False),
        ):
            loop = AgentLoop(config=config)
        loop.registry = registry
        loop._skip_slug_generation = True
        order: list[str] = []
        original_append = loop.log.append

        def append_spy(event_type, *args, **kwargs):
            if event_type == sev.STEP_END:
                order.append(sev.STEP_END)
            return original_append(event_type, *args, **kwargs)

        loop.log.append = append_spy
        loop.tracker.affect_controller.set_listener(
            lambda snapshot: order.append(snapshot.reason),
            emit_current=False,
        )
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "echo", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        loop.run("do something")

        assert order.count("drift") == 1
        drift_index = order.index("drift")
        assert order[drift_index - 1] == sev.STEP_END

    def test_pause_during_tool_suppresses_post_tool_thinking_and_drift(self):
        """Pausing inside a tool turn must leave the visible state paused until resume."""
        tool = FakeTool(name="echo", result="echoed!")
        registry = ToolRegistry()
        registry.register(tool)
        events: list[str] = []
        loop = _make_loop(registry=registry)

        class _Affect:
            def context_line(self) -> str:
                return "Affect: test"

            def drift(self) -> None:
                events.append("drift")

        def on_tool_start(_name, _desc, _args) -> None:
            events.append("tool_start")
            loop.pause()

        callbacks = AgentCallbacks(
            on_process_state_changed=lambda snap: events.append(f"process:{snap.state}"),
            on_tool_start=on_tool_start,
            on_tool_end=lambda _name, _result: events.append("tool_end"),
        )
        loop.callbacks = callbacks
        loop._process.set_listener(loop.callbacks.on_process_state_changed)
        loop.tracker.affect_controller = _Affect()
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "echo", "{}")]),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]
        thread = threading.Thread(target=lambda: loop.run("do something"))

        thread.start()
        deadline = time.time() + 2.0
        while time.time() < deadline and not loop._pause_checkpoint.is_set():
            time.sleep(0.01)

        assert loop._pause_checkpoint.is_set()
        assert loop._pause_event.is_set() is False
        snapshot = list(events)

        loop.inject_and_resume("continue")
        thread.join(timeout=2.0)

        assert not thread.is_alive()
        pause_index = snapshot.index("process:paused")
        assert "process:thinking" not in snapshot[pause_index + 1:]
        assert "drift" not in snapshot[pause_index + 1:]

    def test_pause_race_cannot_publish_post_tool_thinking_after_paused(self):
        """Pause state and post-tool thinking must be ordered by one shared gate."""
        loop = _make_loop()
        events: list[str] = []
        loop.callbacks = AgentCallbacks(
            on_process_state_changed=lambda snap: events.append(f"process:{snap.state}")
        )
        loop._process.set_listener(loop.callbacks.on_process_state_changed)
        loop._process.tool_started("echo")
        events.clear()
        race_event = _PauseAfterIsSet(loop)
        loop._lifecycle.pause_event = race_event

        loop._lifecycle.tool_bookkeeping_finished()
        assert race_event.pause_finished.wait(timeout=1.0)

        if "process:paused" in events:
            pause_index = events.index("process:paused")
            assert "process:thinking" not in events[pause_index + 1:]

    def test_pause_race_cannot_drift_after_paused(self):
        """Affect drift must be serialized with pause, same as process transitions."""
        loop = _make_loop()
        events: list[str] = []

        class _Affect:
            def drift(self) -> None:
                events.append("drift")

        loop.tracker.affect_controller = _Affect()
        loop.callbacks = AgentCallbacks(
            on_process_state_changed=lambda snap: events.append(f"process:{snap.state}")
        )
        loop._process.set_listener(loop.callbacks.on_process_state_changed)
        events.clear()
        race_event = _PauseAfterIsSet(loop)
        loop._lifecycle.pause_event = race_event

        loop._continuing_step_finished(1, 1)
        assert race_event.pause_finished.wait(timeout=1.0)

        if "process:paused" in events:
            pause_index = events.index("process:paused")
            assert "drift" not in events[pause_index + 1:]

    def test_paused_multi_tool_turn_does_not_start_later_tool_process_state(self):
        """A pause between tool calls must keep the process channel paused."""
        tool_a = FakeTool(name="tool_a", result="result a")
        tool_b = FakeTool(name="tool_b", result="result b")
        registry = ToolRegistry()
        registry.register(tool_a)
        registry.register(tool_b)
        loop = _make_loop(registry=registry)
        events: list[str] = []

        def on_tool_end(name: str, _result: str) -> None:
            events.append(f"tool_end:{name}")
            if name == "tool_a":
                loop.pause()

        loop.callbacks = AgentCallbacks(
            on_process_state_changed=lambda snap: events.append(f"process:{snap.state}"),
            on_tool_end=on_tool_end,
        )
        loop._process.set_listener(loop.callbacks.on_process_state_changed)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(
                None,
                tool_calls=[
                    _make_tool_call("tc1", "tool_a", "{}"),
                    _make_tool_call("tc2", "tool_b", "{}"),
                ],
            ),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]
        thread = threading.Thread(target=lambda: loop.run("do something"))

        thread.start()
        deadline = time.time() + 2.0
        while time.time() < deadline and not loop._pause_checkpoint.is_set():
            time.sleep(0.01)

        assert loop._pause_checkpoint.is_set()
        snapshot = list(events)

        loop.inject_and_resume("continue")
        thread.join(timeout=2.0)

        assert not thread.is_alive()
        pause_index = snapshot.index("process:paused")
        assert "process:tool:tool_b" not in snapshot[pause_index + 1:]
        assert "process:thinking" not in snapshot[pause_index + 1:]

    def test_pause_returns_while_process_listener_is_blocked(self):
        """UI pause must not wait behind a worker-held listener callback."""
        loop = _make_loop()
        events: list[str] = []
        listener_entered = threading.Event()
        release_listener = threading.Event()
        pause_returned = threading.Event()

        def on_process(snapshot) -> None:
            events.append(f"process:{snapshot.state}")
            if snapshot.state == "thinking":
                listener_entered.set()
                release_listener.wait(timeout=2.0)

        loop.callbacks = AgentCallbacks(on_process_state_changed=on_process)
        loop._process.set_listener(loop.callbacks.on_process_state_changed)
        loop._process.tool_started("echo")
        worker = threading.Thread(target=loop._lifecycle.tool_bookkeeping_finished)
        worker.start()
        assert listener_entered.wait(timeout=1.0)

        def pause_from_ui_thread() -> None:
            loop.pause()
            pause_returned.set()

        pause_thread = threading.Thread(target=pause_from_ui_thread)
        pause_thread.start()
        returned_before_listener_released = pause_returned.wait(timeout=0.2)
        release_listener.set()
        worker.join(timeout=2.0)
        pause_thread.join(timeout=2.0)

        assert returned_before_listener_released
        assert not worker.is_alive()
        assert not pause_thread.is_alive()
        assert loop._pause_event.is_set() is False
        assert events[-1] == "process:paused"

    def test_process_listener_can_reenter_inject_and_resume(self):
        """Lifecycle publication must not hold a lock while invoking process listeners."""
        loop = _make_loop()
        events: list[str] = []
        injected = [False]

        def on_process(snapshot) -> None:
            events.append(f"process:{snapshot.state}")
            if snapshot.state == "thinking" and not injected[0]:
                injected[0] = True
                loop.inject_and_resume("continue from callback")
                events.append("inject_returned")

        loop.callbacks = AgentCallbacks(on_process_state_changed=on_process)
        loop._process.set_listener(loop.callbacks.on_process_state_changed)
        loop.log.append(sev.TURN_START, {"turn": 1})
        loop.log.append(sev.STEP_START, {"turn": 1, "step": 1})
        worker = threading.Thread(target=loop._lifecycle.api_attempt_started, daemon=True)

        worker.start()
        worker.join(timeout=1.0)

        assert not worker.is_alive()
        assert "inject_returned" in events

    def test_affect_listener_can_reenter_inject_and_resume(self):
        """Affect drift publication must not hold a lock across affect listeners."""
        loop = _make_loop()
        events: list[str] = []

        class _Library:
            def resolve(self, vector, _current_id, _hysteresis):
                return "steady", ImageAsset("steady", Path("steady.png"))

        def on_affect(snapshot) -> None:
            events.append(f"affect:{snapshot.reason}")
            if snapshot.reason == "drift":
                loop.inject_and_resume("continue from affect")
                events.append("inject_returned")

        loop.tracker.affect_controller = AffectController(
            _Library(),
            config=AffectConfig(drift_pull=0.1, drift_noise=0.0),
            baseline=AffectVector(0.0, 0.0, 0.0),
            current=AffectVector(0.5, 0.0, 0.0),
            on_change=lambda _snapshot: None,
        )
        loop.tracker.affect_controller.set_listener(on_affect, emit_current=False)
        loop.log.append(sev.TURN_START, {"turn": 1})
        loop.log.append(sev.STEP_START, {"turn": 1, "step": 1})
        worker = threading.Thread(
            target=lambda: loop._continuing_step_finished(1, 1),
            daemon=True,
        )

        worker.start()
        worker.join(timeout=1.0)

        assert not worker.is_alive()
        assert events == ["affect:drift", "inject_returned"]

    def test_pause_during_tool_resolution_prevents_late_tool_after_pause_returns(self):
        """Pause must serialize invalidation with tool-state mutation, not just dequeue."""
        loop = _make_loop()
        events: list[str] = []
        resolver_entered = threading.Event()
        release_resolver = threading.Event()

        class _BlockingLibrary:
            def __init__(self, delegate) -> None:
                self._delegate = delegate

            def resolve(self, state: str):
                if state == "tool:echo":
                    resolver_entered.set()
                    release_resolver.wait(timeout=2.0)
                return self._delegate.resolve(state)

        loop._process._library = _BlockingLibrary(loop._process._library)
        loop.callbacks = AgentCallbacks(
            on_process_state_changed=lambda snap: events.append(f"process:{snap.state}")
        )
        loop._process.set_listener(loop.callbacks.on_process_state_changed)
        worker = threading.Thread(target=lambda: loop._lifecycle.tool_started("echo"))
        worker.start()
        assert resolver_entered.wait(timeout=1.0)

        def pause_from_ui_thread() -> None:
            loop.pause()
            events.append("pause_returned")

        pause_thread = threading.Thread(target=pause_from_ui_thread)
        pause_thread.start()
        release_resolver.set()
        worker.join(timeout=2.0)
        pause_thread.join(timeout=2.0)

        assert not worker.is_alive()
        assert not pause_thread.is_alive()
        assert "pause_returned" in events
        pause_index = events.index("pause_returned")
        assert "process:tool:echo" not in events[pause_index + 1:]

    def test_pause_during_affect_resolution_prevents_late_drift_after_pause_returns(self):
        """Pause must serialize invalidation with affect drift mutation."""
        loop = _make_loop()
        events: list[str] = []
        resolver_entered = threading.Event()
        release_resolver = threading.Event()

        class _BlockingVadLibrary:
            def resolve(self, vector, _current_id, _hysteresis):
                resolver_entered.set()
                release_resolver.wait(timeout=2.0)
                return "steady", ImageAsset("steady", Path("steady.png"))

        loop.tracker.affect_controller = AffectController(
            _BlockingVadLibrary(),
            config=AffectConfig(drift_pull=0.1, drift_noise=0.0),
            baseline=AffectVector(0.0, 0.0, 0.0),
            current=AffectVector(0.5, 0.0, 0.0),
            on_change=lambda _snapshot: None,
        )
        loop.tracker.affect_controller.set_listener(
            lambda snapshot: events.append(f"affect:{snapshot.reason}"),
            emit_current=False,
        )
        loop.log.append(sev.TURN_START, {"turn": 1})
        loop.log.append(sev.STEP_START, {"turn": 1, "step": 1})
        worker = threading.Thread(target=lambda: loop._continuing_step_finished(1, 1))
        worker.start()
        assert resolver_entered.wait(timeout=1.0)

        def pause_from_ui_thread() -> None:
            loop.pause()
            events.append("pause_returned")

        pause_thread = threading.Thread(target=pause_from_ui_thread)
        pause_thread.start()
        release_resolver.set()
        worker.join(timeout=2.0)
        pause_thread.join(timeout=2.0)

        assert not worker.is_alive()
        assert not pause_thread.is_alive()
        assert "pause_returned" in events
        pause_index = events.index("pause_returned")
        assert "affect:drift" not in events[pause_index + 1:]

    def test_pause_waits_until_accepted_callback_is_ordered_not_completed(self):
        """Pause may not return in the post-unlock/pre-callback publication window."""
        loop = _make_loop()
        barrier_lock = _ExitBarrierLock()
        loop._lifecycle._state_lock = barrier_lock
        callback_entered = threading.Event()
        release_callback = threading.Event()
        pause_returned = threading.Event()

        def prepare():
            barrier_lock.arm_current_exit()

            def callback() -> None:
                callback_entered.set()
                release_callback.wait(timeout=2.0)

            return callback

        generation = loop._lifecycle._generation
        worker = threading.Thread(
            target=lambda: loop._lifecycle.enqueue("running", generation, prepare)
        )
        worker.start()
        assert barrier_lock.entered.wait(timeout=1.0)

        pause_thread = threading.Thread(
            target=lambda: (loop.pause(), pause_returned.set())
        )
        pause_thread.start()
        assert not pause_returned.wait(timeout=0.2)

        barrier_lock.release.set()
        assert callback_entered.wait(timeout=1.0)
        assert pause_returned.wait(timeout=1.0)
        assert worker.is_alive()
        release_callback.set()
        worker.join(timeout=2.0)
        pause_thread.join(timeout=2.0)

        assert not worker.is_alive()
        assert not pause_thread.is_alive()

    def test_pause_waits_for_callback_entry_not_pre_call_marker(self):
        """Pause must not return after the marker but before callback entry."""
        loop = _make_loop()
        pre_entry_reached = threading.Event()
        release_entry = threading.Event()
        callback_entered = threading.Event()
        release_callback_body = threading.Event()
        pause_returned = threading.Event()
        original_mark_started = loop._lifecycle._mark_callback_entered

        def freeze_before_entry() -> None:
            pre_entry_reached.set()
            release_entry.wait(timeout=2.0)

        def mark_started(event) -> None:
            original_mark_started(event)
            callback_entered.set()

        loop._lifecycle.before_callback_entry = freeze_before_entry
        loop._lifecycle._mark_callback_entered = mark_started

        def prepare():
            def callback() -> None:
                release_callback_body.wait(timeout=2.0)

            return callback

        generation = loop._lifecycle._generation
        worker = threading.Thread(
            target=lambda: loop._lifecycle.enqueue("running", generation, prepare)
        )
        worker.start()
        assert pre_entry_reached.wait(timeout=1.0)

        pause_thread = threading.Thread(
            target=lambda: (loop.pause(), pause_returned.set())
        )
        pause_thread.start()
        assert not pause_returned.wait(timeout=0.2)
        assert not callback_entered.is_set()

        release_entry.set()
        assert callback_entered.wait(timeout=1.0)
        assert pause_returned.wait(timeout=1.0)
        assert worker.is_alive()
        release_callback_body.set()
        worker.join(timeout=2.0)
        pause_thread.join(timeout=2.0)

        assert not worker.is_alive()
        assert not pause_thread.is_alive()

    def test_legacy_affect_drift_is_not_published_after_pause_returns(self):
        """One-piece legacy drift cannot safely mutate outside lifecycle acceptance."""
        loop = _make_loop()
        events: list[str] = []
        barrier_lock = _ExitBarrierLock()
        loop._lifecycle._state_lock = barrier_lock

        class _LegacyAffect:
            @property
            def drift(self):
                barrier_lock.arm_current_exit()

                def callback() -> None:
                    events.append("legacy_drift")

                return callback

        loop.tracker.affect_controller = _LegacyAffect()
        loop.log.append(sev.TURN_START, {"turn": 1})
        loop.log.append(sev.STEP_START, {"turn": 1, "step": 1})
        worker = threading.Thread(target=lambda: loop._continuing_step_finished(1, 1))
        worker.start()
        if not barrier_lock.entered.wait(timeout=0.2):
            worker.join(timeout=2.0)
            assert not worker.is_alive()
            assert events == []
            return

        pause_thread = threading.Thread(
            target=lambda: (loop.pause(), events.append("pause_returned"))
        )
        pause_thread.start()
        assert not any(event == "pause_returned" for event in events)
        barrier_lock.release.set()
        worker.join(timeout=2.0)
        pause_thread.join(timeout=2.0)

        assert not worker.is_alive()
        assert not pause_thread.is_alive()
        pause_index = events.index("pause_returned")
        assert "legacy_drift" not in events[pause_index + 1:]


class TestParentForkCapture:
    def test_spawn_fork_uses_request_before_assistant_tool_response(self):
        """A child spawned by a tool call must inherit the request prefix, not its response."""
        tool = FakeTool(name="write_handoff", result=f"report {WRITE_HANDOFF_SENTINEL}")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "write_handoff", "{}")]),
        ]

        loop.run("delegate this")
        messages_before = loop._messages
        surface_before = loop.log.surface.nodes
        fork = loop.capture_parent_fork("worker_spawn", "spawn")

        assert fork.request["messages"][1] == {"role": "user", "content": "delegate this"}
        assert all(message.get("role") != "assistant" for message in fork.request["messages"])
        assert fork.parent_cut_seq == surface_before[0]
        assert fork.parent_surface_generation == 0
        assert loop.log.surface.nodes == surface_before
        assert loop._messages is messages_before
        branch = loop.log.branch_event("worker_spawn")
        assert branch is not None
        assert branch.data["parent_branch"] == "main"
        assert branch.data["parent_cut_seq"] == fork.parent_cut_seq

    def test_stable_idle_fork_includes_last_completed_surface(self):
        """An idle /wtf fork sees the last assistant reply, not a stale API snapshot."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _make_response(
            f"Complete. {TASK_END_FLAG}"
        )

        loop.run("finish this")
        fork = loop.capture_parent_fork("worker_idle", "stable")

        assert fork.request["messages"][1:3] == [
            {"role": "user", "content": "finish this"},
            {"role": "assistant", "content": f"Complete. {TASK_END_FLAG}"},
        ]
        assert loop.log.branch_event("worker_idle") is not None
        provider = loop.parent_context_provider
        assert provider.get_surface_generation() == loop.log.surface.generation

    def test_wait_for_pause_checkpoint_requires_the_checkpoint_not_pause_state(self):
        """Pause observation must not accidentally resume the loop."""
        loop = _make_loop()
        loop.pause()

        assert loop.wait_for_pause_checkpoint(0) is False
        assert loop._pause_event.is_set() is False
        loop._pause_checkpoint.set()
        assert loop.wait_for_pause_checkpoint(0) is True
        assert loop._pause_event.is_set() is False

    def test_stable_open_turn_requires_safe_checkpoint_while_running(self):
        """A live turn cannot be captured before its response bookkeeping is safe."""
        loop = _make_loop()
        loop.log.append(sev.TURN_START, {"turn": 1})
        loop._log_user_message("user", "still running", "human")

        with pytest.raises(RuntimeError, match="safe checkpoint"):
            loop.capture_parent_fork("worker_unsafe", "stable")

        assert loop.log.branch_event("worker_unsafe") is None

    def test_stable_fork_excludes_empty_step_opened_before_pause(self):
        """The pause checkpoint cannot add a phantom message to a stable child prefix."""
        loop = _make_loop()
        loop.log.append(sev.TURN_START, {"turn": 1})
        loop._log_user_message("user", "pause after this", "human")
        loop.log.append(sev.STEP_START, {"turn": 1, "step": 1})
        loop.pause()
        loop._pause_checkpoint.set()

        fork = loop.capture_parent_fork("worker_paused", "stable")

        assert fork.request["messages"] == [
            loop._header_message(),
            {"role": "user", "content": "pause after this"},
        ]
        assert fork.parent_cut_seq == loop.log.surface.nodes[-1]
