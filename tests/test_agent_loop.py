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
from agent.loop import AgentCallbacks, AgentConfig, AgentLoop
from agent.protocol import SideEffect, ToolResult
from tools.write_handoff import WriteHandoffTool
from agent.registry import ToolRegistry


class FakeTool(BaseTool):
    def __init__(self, name="echo", description="Echoes input", result="tool ran"):
        self.name = name
        self.description = description
        self._parameters = {"type": "object", "properties": {}, "required": []}
        self._result = result
        self.calls: list[dict] = []

    def run(self, **kwargs) -> "str | ToolResult":
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
    if "write_handoff" not in {name for name, _ in real_registry.list_tools()}:
        real_registry.register(WriteHandoffTool(handoff_path=None))

    fake_tracker = MagicMock()
    fake_tracker.expression_controller = None

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


def _exit_response(content: str = "Done.", prompt_tokens: int = 10, completion_tokens: int = 5):
    """A response where the model calls write_handoff to end the turn."""
    return _make_response(
        None,
        tool_calls=[_make_tool_call("tc_exit", "write_handoff", json.dumps({"content": content}))],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


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
            _exit_response("Done."),
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
            _exit_response("Done."),
        ]

        loop.run("do something")

        tool_msgs = [m for m in loop._messages if m.get("role") == "tool" and m.get("tool_call_id") != "tc_exit"]
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
            _exit_response("Done."),
        ]

        loop.run("do something")

        echo_starts = [(n, d, a) for n, d, a in starts if n != "write_handoff"]
        echo_ends = [(n, r) for n, r in ends if n != "write_handoff"]
        assert echo_starts == [("echo", "Echoes input", '{"x": 1}')]
        assert echo_ends == [("echo", "echoed!")]

    def test_tracker_records_tool_start_and_end(self):
        tool = FakeTool(name="echo", result="echoed!")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "echo", "{}")]),
            _exit_response("Done."),
        ]

        loop.run("do something")

        loop.tracker.record_tool_start.assert_any_call("echo", "Echoes input", "{}")
        loop.tracker.record_tool_end.assert_any_call("echo", "echoed!")

    def test_unknown_tool_call_yields_error_result_and_loop_continues(self):
        registry = ToolRegistry()
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "nonexistent", "{}")]),
            _exit_response("Done."),
        ]

        loop.run("do something")

        tool_msgs = [m for m in loop._messages if m.get("role") == "tool"]
        assert tool_msgs[0]["content"] == "Error: unknown tool 'nonexistent'"

    def test_malformed_tool_arguments_yield_error_result_and_loop_continues(self):
        tool = FakeTool(name="ask_user")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(
                None,
                tool_calls=[
                    _make_tool_call(
                        "tc_bad_json",
                        "ask_user",
                        '{"question": "Choose", "options" [{"label": "A"}]}',
                    )
                ],
            ),
            _exit_response("Recovered."),
        ]

        result = loop.run("ask me something")

        assert result == "Recovered."
        assert tool.calls == []
        retry_messages = loop.client.chat.completions.create.call_args_list[1].kwargs["messages"]
        error_reply = next(
            msg for msg in retry_messages if msg.get("tool_call_id") == "tc_bad_json"
        )
        assert error_reply["role"] == "tool"
        assert error_reply["content"].startswith(
            "Error: invalid JSON arguments for tool 'ask_user':"
        )

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
            _exit_response("Done."),
        ]

        loop.run("do something")

        assert tool_a.calls == [{}]
        assert tool_b.calls == [{}]
        tool_msgs = [m for m in loop._messages if m.get("role") == "tool" and m.get("tool_call_id") != "tc_exit"]
        assert [m["tool_call_id"] for m in tool_msgs] == ["tc1", "tc2"]


class TestWriteHandoffExit:
    """write_handoff tool call must terminate the loop immediately — no further
    API calls, transcript stays well-formed, content is returned."""

    def test_run_returns_content_and_makes_no_further_api_call(self):
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[
                _make_tool_call("tc1", "write_handoff", json.dumps({"content": "Handoff written."}))
            ]),
        ]

        result = loop.run("do something")

        assert result == "Handoff written."
        assert loop.client.chat.completions.create.call_count == 1

    def test_result_is_exactly_the_content_passed_to_write_handoff(self):
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = _make_response(
            None,
            tool_calls=[_make_tool_call("tc1", "write_handoff", json.dumps({"content": "my content"}))],
        )

        result = loop.run("do something")

        assert result == "my content"

    def test_transcript_has_well_formed_tool_reply(self):
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[
                _make_tool_call("tc1", "write_handoff", json.dumps({"content": "Handoff written."}))
            ]),
        ]

        loop.run("do something")

        tool_msgs = [m for m in loop._messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tc1"
        assert tool_msgs[0]["content"] == "Handoff written."

    def test_on_done_callback_fires_with_content(self):
        done_calls = []
        callbacks = AgentCallbacks(on_done=lambda r: done_calls.append(r))

        loop = _make_loop()
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[
                _make_tool_call("tc1", "write_handoff", json.dumps({"content": "Handoff written."}))
            ]),
        ]

        loop.run("do something")

        assert done_calls == ["Handoff written."]

    def test_bookkeeping_fires_on_handoff_path(self):
        """record_assistant and on_token_update must fire on the write_handoff
        termination path, same as every other early-exit path."""
        token_updates = []
        callbacks = AgentCallbacks(
            on_token_update=lambda p, c, cost, t, cached=0: token_updates.append((p, c, cost, t))
        )

        loop = _make_loop()
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(
                None,
                tool_calls=[_make_tool_call("tc1", "write_handoff", json.dumps({"content": "done"}))],
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

        warnings = []
        done_calls = []
        handoff_calls = []
        callbacks = AgentCallbacks(
            on_assistant_text=lambda t: warnings.append(t),
            on_done=lambda result: done_calls.append(result),
            on_handoff=lambda: handoff_calls.append(True),
        )

        loop = _make_loop(reserve_tokens=10, project_path=tmp_path)
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[
                _make_tool_call("tc1", "write_handoff", json.dumps({"content": large_report}))
            ]),
        ]

        result = loop.run("do something")

        tool_msgs = [m for m in loop._messages if m.get("role") == "tool"]
        assert "OUTPUT TRUNCATED" in tool_msgs[0]["content"]
        assert any("[output filter]" in w for w in warnings)
        # Final returned/on_done value is the full, unfiltered report (JSONL/caller-facing).
        assert result == large_report
        assert done_calls == [large_report]
        assert handoff_calls == [True]

    def test_non_write_handoff_tool_does_not_exit_loop(self):
        """Only the write_handoff tool triggers END_TURN; other tools continue the loop."""
        tool = FakeTool(name="spawn_subagent", result="Subagent done.\nreport text")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "spawn_subagent", "{}")]),
            _exit_response("Done."),
        ]

        result = loop.run("spawn a subagent")

        # Must have continued to the second LLM call — spawn_subagent does not exit.
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
            _exit_response("Done."),
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
            _exit_response("Done.", prompt_tokens=50),
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
            _exit_response("Done.", prompt_tokens=50),
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
            _exit_response("Done.", prompt_tokens=50),
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


class TestToolResultIsolation:
    """Tool result text never causes loop termination — only write_handoff does."""

    def test_arbitrary_tool_result_does_not_terminate_loop(self):
        """A tool that returns arbitrary text (even old-style sentinel strings) does
        not exit the loop — only write_handoff with SideEffect.END_TURN does."""
        tool = FakeTool(name="read", result="file content <<END_OF_RESPONSE>> more text")
        registry = ToolRegistry()
        registry.register(tool)
        loop = _make_loop(registry=registry)
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "read", "{}")]),
            _exit_response("All done."),
        ]

        result = loop.run("read a file")

        # Must have made TWO LLM calls — tool result alone never exits.
        assert loop.client.chat.completions.create.call_count == 2
        assert result == "All done."

    def test_on_tool_end_callback_receives_full_result(self):
        """on_tool_end must receive the complete tool output string."""
        specific_text = "data __some_marker__ end"
        tool = FakeTool(name="read", result=specific_text)
        registry = ToolRegistry()
        registry.register(tool)

        ends = []
        callbacks = AgentCallbacks(on_tool_end=lambda name, result: ends.append(result))
        loop = _make_loop(registry=registry)
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "read", "{}")]),
            _exit_response("Done."),
        ]

        loop.run("read a file")

        assert ends[0] == specific_text


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
        loop = _make_loop()
        loop._messages = [{"role": "system", "content": "sys"}]
        tc_a = _make_tool_call("call_a", "reload_skills")
        tc_b = _make_tool_call("call_b", "read", '{"file_path": "a"}')
        message = SimpleNamespace(tool_calls=[tc_a, tc_b], content=None)
        response = _make_response(None, tool_calls=[tc_a, tc_b])
        loop.registry._tools = {}
        loop.registry.dispatch = MagicMock(side_effect=[
            ToolResult(output="", side_effect=SideEffect.RELOAD_SKILLS),
            "ok",
        ])
        loop._rebuild_for_reload = MagicMock(return_value=(set(), set(), []))
        self._open_turn(loop)

        loop._dispatch_tool_calls(message, response, [])

        roles = [m["role"] for m in loop._messages]
        # Both tool results precede the deferred system notification.
        assert roles.index("system", 1) > roles.index("tool")
        assert roles[-1] == "system"

    def test_write_handoff_tool_call_ends_dispatch(self):
        loop = _make_loop()
        self._open_turn(loop)
        loop._messages = [{"role": "system", "content": "sys"}]
        tc = _make_tool_call("call_h", "write_handoff", json.dumps({"content": "handoff body"}))
        message = SimpleNamespace(tool_calls=[tc], content=None)
        response = _make_response(None, tool_calls=[tc])
        loop.registry._tools = {}
        loop.registry.dispatch = MagicMock(
            return_value=ToolResult(output="handoff body", side_effect=SideEffect.END_TURN)
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

    def test_main_loop_binds_expression_controller_before_registry_build(self, tmp_path):
        """A normal main loop must expose emote when config allowlists it."""
        from agent.expression import ExpressionController

        config = AgentConfig(
            api_key="test-key",
            project_path=tmp_path,
            system_prompt="{tools_and_skills}",
            tools=["emote"],
        )

        with patch("openai.OpenAI"):
            loop = AgentLoop(config=config)

        names = {name for name, _description in loop.registry.list_tools()}
        assert isinstance(loop.tracker.expression_controller, ExpressionController)
        assert "emote" in names


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
            _exit_response("Done."),
        ]

        loop.run("do something")

        assert events.index("process:thinking") < events.index("api")
        assert events.index("process:tool:echo") < events.index("tool_start:echo")
        assert events.index("tool_end:echo") < events.index("process:thinking", 3)
        assert events[-2:] == ["process:idle", "done"]

    def test_pause_during_tool_suppresses_post_tool_thinking(self):
        """Pausing inside a tool turn must leave the visible state paused until resume."""
        tool = FakeTool(name="echo", result="echoed!")
        registry = ToolRegistry()
        registry.register(tool)
        events: list[str] = []
        loop = _make_loop(registry=registry)

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
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[_make_tool_call("tc1", "echo", "{}")]),
            _exit_response("Done."),
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
            _exit_response("Done."),
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


class TestParentForkCapture:
    def test_spawn_fork_uses_request_before_assistant_tool_response(self):
        """A child spawned by a tool call must inherit the request prefix, not its response."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_response(None, tool_calls=[
                _make_tool_call("tc1", "write_handoff", json.dumps({"content": "report"}))
            ]),
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
        loop.client.chat.completions.create.return_value = _exit_response("Complete.")

        loop.run("finish this")
        fork = loop.capture_parent_fork("worker_idle", "stable")

        assert fork.request["messages"][1] == {"role": "user", "content": "finish this"}
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
