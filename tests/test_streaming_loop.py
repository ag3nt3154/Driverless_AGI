"""tests/test_streaming_loop.py — _consume_stream accumulation + streaming run() path."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.loop import AgentCallbacks, AgentConfig, AgentLoop


def _make_loop(callbacks=None, **config_kwargs) -> AgentLoop:
    """Create an AgentLoop with all heavy dependencies mocked out."""
    config = AgentConfig(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        **config_kwargs,
    )
    fake_registry = MagicMock()
    fake_registry.get_openai_tools_list.return_value = []
    fake_registry.list_tools.return_value = []
    fake_tracker = MagicMock()
    with (
        patch("agent.loop.SessionTracker", return_value=fake_tracker),
        patch("openai.OpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        loop = AgentLoop(
            config=config,
            callbacks=callbacks,
            _registry=fake_registry,
            _tracker=fake_tracker,
        )
    loop.tracker = fake_tracker
    loop.registry = fake_registry
    return loop


# ── Chunk factories ──────────────────────────────────────────────────────────

def _chunk(content=None, reasoning=None, tool_calls=None, usage=None, no_choices=False):
    """Build a fake streaming chunk. no_choices=True mimics the trailing
    usage-only chunk OpenRouter/OpenAI send with choices=[]."""
    if no_choices:
        return SimpleNamespace(choices=[], usage=usage)
    delta = SimpleNamespace(
        content=content,
        reasoning=reasoning,
        reasoning_content=None,
        tool_calls=tool_calls,
        model_extra={},
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


def _tc_delta(index, id=None, name=None, arguments=None):
    """One partial tool-call inside a chunk's delta.tool_calls list."""
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=fn)


def _usage(prompt=10, completion=5):
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion,
        cost=None, completion_tokens_details=None,
    )


# ── _consume_stream unit tests ───────────────────────────────────────────────

class TestConsumeStream:
    def test_content_accumulated_and_deltas_fired(self):
        deltas: list[str] = []
        cb = AgentCallbacks(on_assistant_text_delta=deltas.append)
        loop = _make_loop(callbacks=cb)
        msg, usage = loop._consume_stream(iter([
            _chunk(content="Hel"), _chunk(content="lo"), _chunk(content="!"),
        ]))
        assert msg.content == "Hello!"
        assert deltas == ["Hel", "lo", "!"]
        assert msg.tool_calls is None
        assert usage is None

    def test_reasoning_accumulated_and_deltas_fired(self):
        deltas: list[str] = []
        cb = AgentCallbacks(on_reasoning_delta=deltas.append)
        loop = _make_loop(callbacks=cb)
        msg, _ = loop._consume_stream(iter([
            _chunk(reasoning="think"), _chunk(reasoning="ing"), _chunk(content="done"),
        ]))
        assert msg.reasoning_content == "thinking"
        assert deltas == ["think", "ing"]
        assert msg.content == "done"

    def test_tool_calls_reassembled_by_index(self):
        loop = _make_loop()
        msg, _ = loop._consume_stream(iter([
            _chunk(tool_calls=[_tc_delta(0, id="call_1", name="read", arguments='{"pa')]),
            _chunk(tool_calls=[_tc_delta(0, arguments='th": "x.py"}')]),
            _chunk(tool_calls=[_tc_delta(1, id="call_2", name="bash", arguments='{"command": "ls"}')]),
        ]))
        assert len(msg.tool_calls) == 2
        assert msg.tool_calls[0].id == "call_1"
        assert msg.tool_calls[0].function.name == "read"
        assert msg.tool_calls[0].function.arguments == '{"path": "x.py"}'
        assert msg.tool_calls[1].function.name == "bash"

    def test_trailing_usage_chunk_captured(self):
        loop = _make_loop()
        msg, usage = loop._consume_stream(iter([
            _chunk(content="hi"),
            _chunk(no_choices=True, usage=_usage(prompt=42, completion=7)),
        ]))
        assert usage.prompt_tokens == 42
        assert usage.completion_tokens == 7

    def test_missing_usage_yields_none(self):
        loop = _make_loop()
        _, usage = loop._consume_stream(iter([_chunk(content="hi")]))
        assert usage is None

    def test_stream_start_and_end_fired_once(self):
        events: list[str] = []
        cb = AgentCallbacks(
            on_stream_start=lambda: events.append("start"),
            on_stream_end=lambda: events.append("end"),
        )
        loop = _make_loop(callbacks=cb)
        loop._consume_stream(iter([_chunk(content="x")]))
        assert events == ["start", "end"]

    def test_stream_end_fires_even_when_iteration_raises(self):
        events: list[str] = []
        cb = AgentCallbacks(on_stream_end=lambda: events.append("end"))
        loop = _make_loop(callbacks=cb)

        def _boom():
            yield _chunk(content="par")
            raise ConnectionError("dropped")

        with pytest.raises(ConnectionError):
            loop._consume_stream(_boom())
        assert events == ["end"]

    def test_empty_stream_gives_ghost_shaped_message(self):
        """No chunks at all → content None, no tool calls — the exact shape
        the existing ghost-response check detects."""
        loop = _make_loop()
        msg, usage = loop._consume_stream(iter([]))
        assert msg.content is None
        assert msg.tool_calls is None
        assert usage is None


import httpx
import openai

from agent.loop import TASK_END_FLAG


def _stream_client(*chunk_lists):
    """Fake OpenAI client whose create() returns successive chunk iterators.
    Asserts stream kwargs are passed. Each call consumes the next chunk list."""
    calls = {"n": 0, "kwargs": []}

    def create(**kwargs):
        calls["kwargs"].append(kwargs)
        i = calls["n"]
        calls["n"] += 1
        item = chunk_lists[i]
        if isinstance(item, Exception):
            raise item
        if callable(item):          # generator factory → mid-stream error support
            return item()
        return iter(item)

    client = MagicMock()
    client.chat.completions.create.side_effect = create
    return client, calls


class TestStreamingRun:
    def test_streaming_turn_end_to_end(self):
        """A streamed text-only turn: deltas fire, final on_assistant_text fires
        with full text, token update uses the trailing usage chunk."""
        deltas: list[str] = []
        finals: list[str] = []
        tokens: list[tuple] = []
        cb = AgentCallbacks(
            on_assistant_text_delta=deltas.append,
            on_assistant_text=finals.append,
            on_token_update=lambda i, o, c, t: tokens.append((i, o)),
        )
        loop = _make_loop(callbacks=cb, stream=True)
        loop.client, calls = _stream_client([
            _chunk(content="Done. "),
            _chunk(content=TASK_END_FLAG),
            _chunk(no_choices=True, usage=_usage(prompt=33, completion=9)),
        ])
        result = loop.run("do the thing")
        assert result == "Done."
        assert deltas == ["Done. ", TASK_END_FLAG]
        assert any("Done." in f for f in finals)
        assert (33, 9) in tokens
        # The API call itself must request streaming + usage:
        assert calls["kwargs"][0]["stream"] is True
        assert calls["kwargs"][0]["stream_options"] == {"include_usage": True}

    def test_non_streaming_config_never_passes_stream_kwarg(self):
        """config.stream=False (dataclass default) → identical call to today."""
        loop = _make_loop()  # stream defaults False
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=f"ok {TASK_END_FLAG}", tool_calls=[], model_extra={},
            ))],
            usage=_usage(),
        )
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = response
        loop.run("task")
        _, kwargs = loop.client.chat.completions.create.call_args
        assert "stream" not in kwargs
        assert "stream_options" not in kwargs

    def test_streamed_tool_call_dispatches(self):
        """Tool-call deltas reassemble and dispatch through the registry."""
        loop = _make_loop(stream=True)
        loop.registry.dispatch.return_value = "tool ran"
        loop.registry._tools = {}
        loop.client, _ = _stream_client(
            [   # turn 1: a tool call split across chunks
                _chunk(tool_calls=[_tc_delta(0, id="c1", name="bash", arguments='{"comma')]),
                _chunk(tool_calls=[_tc_delta(0, arguments='nd": "echo hi"}')]),
                _chunk(no_choices=True, usage=_usage()),
            ],
            [   # turn 2: finish
                _chunk(content=f"finished {TASK_END_FLAG}"),
                _chunk(no_choices=True, usage=_usage()),
            ],
        )
        result = loop.run("run echo")
        assert result == "finished"
        loop.registry.dispatch.assert_called_once_with(
            "bash", {"command": "echo hi"}
        )

    def test_midstream_connection_error_retries_whole_call(self):
        """A stream that dies mid-iteration is retried from scratch via the
        existing connection-retry path; partial accumulation is discarded."""
        def _dying():
            yield _chunk(content="partial ")
            raise openai.APIConnectionError(request=httpx.Request("POST", "http://test"))

        finals: list[str] = []
        cb = AgentCallbacks(on_assistant_text=finals.append)
        loop = _make_loop(callbacks=cb, stream=True, api_error_retries=3)
        loop.client, calls = _stream_client(
            _dying,
            [
                _chunk(content=f"complete {TASK_END_FLAG}"),
                _chunk(no_choices=True, usage=_usage()),
            ],
        )
        with patch("agent.loop.time.sleep"):  # skip the backoff delay
            result = loop.run("task")
        assert result == "complete"
        assert calls["n"] == 2
        # The partial text must not leak into any final assistant text:
        assert not any("partial" in f for f in finals)

    def test_ghost_stream_retries(self):
        """An empty stream (no content, no tool calls, no usage) is a ghost
        response — silently retried like the blocking path."""
        loop = _make_loop(stream=True)
        loop.client, calls = _stream_client(
            [],  # ghost: zero chunks
            [
                _chunk(content=f"real {TASK_END_FLAG}"),
                _chunk(no_choices=True, usage=_usage()),
            ],
        )
        result = loop.run("task")
        assert result == "real"
        assert calls["n"] == 2
