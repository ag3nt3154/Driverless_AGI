"""tests/test_agent_loop.py — Unit tests for AgentLoop tool dispatch and compaction trigger."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent import session_events as sev
from agent.base_tool import BaseTool
from agent.loop import (
    AgentCallbacks, AgentConfig, AgentLoop,
    AWAIT_USER_FLAG, TASK_END_FLAG, WRITE_HANDOFF_SENTINEL,
    _escape_sentinels,
)
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
        callbacks = AgentCallbacks(on_assistant_text=lambda t: warnings.append(t))

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
        loop.compact_tool = MagicMock()

        loop.run("do something")

        loop.compact_tool.compact.assert_called_once()

    def test_compaction_does_not_fire_below_budget(self):
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
        loop.compact_tool = MagicMock()

        loop.run("do something")

        loop.compact_tool.compact.assert_not_called()

    def test_compaction_disabled_when_context_window_is_zero(self):
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
        loop.compact_tool = MagicMock()

        loop.run("do something")

        loop.compact_tool.compact.assert_not_called()

    def test_compact_context_swallows_errors_and_warns(self):
        loop = _make_loop()
        loop.compact_tool = MagicMock()
        loop.compact_tool.compact.side_effect = RuntimeError("compaction blew up")
        warnings = []
        loop.callbacks = AgentCallbacks(on_assistant_text=lambda t: warnings.append(t))

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
