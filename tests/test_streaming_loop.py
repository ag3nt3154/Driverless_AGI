"""tests/test_streaming_loop.py — _consume_stream accumulation + streaming run() path."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from agent.image_assets import ImageAssetStore, ImageRef
from agent.loop import AgentCallbacks, AgentConfig, AgentLoop
from agent.protocol import SideEffect, ToolResult
from agent.user_input import ImageAttachment


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
    fake_registry._tools = {"write_handoff": SimpleNamespace(description="submit handoff")}

    def _dispatch(name, args):
        if name == "write_handoff":
            return ToolResult(output=args.get("content", ""), side_effect=SideEffect.END_TURN)
        return "tool ran"

    fake_registry.dispatch.side_effect = _dispatch

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
            tracker=fake_tracker,
        )
    loop.tracker = fake_tracker
    loop.registry = fake_registry
    loop._skip_slug_generation = True
    return loop


def _wh_chunks(content: str = "done"):
    """Streaming chunks for a write_handoff tool call that exits the loop."""
    args = json.dumps({"content": content})
    return [
        _chunk(tool_calls=[_tc_delta(0, id="tc_wh", name="write_handoff", arguments=args)]),
        _chunk(no_choices=True, usage=_usage()),
    ]


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
            on_token_update=lambda i, o, c, t, cached=0: tokens.append((i, o)),
        )
        loop = _make_loop(callbacks=cb, stream=True)
        loop.client, calls = _stream_client(
            [   # turn 1: text-only response
                _chunk(content="Done. "),
                _chunk(no_choices=True, usage=_usage(prompt=33, completion=9)),
            ],
            _wh_chunks("Done."),  # turn 2: write_handoff exits loop
        )
        result = loop.run("do the thing")
        assert result == "Done."
        assert deltas == ["Done. "]
        assert any("Done." in f for f in finals)
        assert (33, 9) in tokens
        # The API call itself must request streaming + usage:
        assert calls["kwargs"][0]["stream"] is True
        assert calls["kwargs"][0]["stream_options"] == {"include_usage": True}

    def test_non_streaming_config_never_passes_stream_kwarg(self):
        """config.stream=False (dataclass default) → identical call to today."""
        loop = _make_loop()  # stream defaults False
        _wh_tc = SimpleNamespace(
            id="tc_end",
            function=SimpleNamespace(name="write_handoff", arguments=json.dumps({"content": "ok"})),
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=None, tool_calls=[_wh_tc], model_extra={}, reasoning_content=None,
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

        dispatched = []
        _orig_dispatch = loop.registry.dispatch.side_effect

        def _tracking_dispatch(name, args):
            if name != "write_handoff":
                dispatched.append((name, args))
            return _orig_dispatch(name, args)

        loop.registry.dispatch.side_effect = _tracking_dispatch
        loop.registry._tools = {}
        loop.client, _ = _stream_client(
            [   # turn 1: a tool call split across chunks
                _chunk(tool_calls=[_tc_delta(0, id="c1", name="bash", arguments='{"comma')]),
                _chunk(tool_calls=[_tc_delta(0, arguments='nd": "echo hi"}')]),
                _chunk(no_choices=True, usage=_usage()),
            ],
            _wh_chunks("finished"),  # turn 2: write_handoff exits
        )
        result = loop.run("run echo")
        assert result == "finished"
        assert dispatched == [("bash", {"command": "echo hi"})]

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
            _wh_chunks("complete"),
        )
        with patch("agent._request_executor.time.sleep"):  # skip the backoff delay
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
            _wh_chunks("real"),
        )
        result = loop.run("task")
        assert result == "real"
        assert calls["n"] == 2

    def test_midstream_httpx_error_retries_then_succeeds(self):
        """A raw httpx.HTTPError (not wrapped by the openai SDK — the failure
        mode a dropped transport connection mid-iteration actually surfaces
        as) is caught by the widened except tuple and retried, same as an
        openai.APIConnectionError."""
        def _dying():
            yield _chunk(content="partial ")
            raise httpx.ReadError("connection reset")

        loop = _make_loop(stream=True, api_error_retries=3)
        loop.client, calls = _stream_client(
            _dying,
            _wh_chunks("complete"),
        )
        with patch("agent._request_executor.time.sleep"):
            result = loop.run("task")
        assert result == "complete"
        assert calls["n"] == 2

    def test_midstream_httpx_error_exhausts_retries_and_raises(self):
        """A persistent httpx.HTTPError is bounded by api_error_retries, not
        retried forever — mirrors the existing openai.APIConnectionError
        exhaustion behavior (see test_continuation.py::test_exhausted_retries_raises)."""
        def _always_dying():
            yield _chunk(content="x")
            raise httpx.ReadError("connection reset")

        loop = _make_loop(stream=True, api_error_retries=2)
        loop.client, calls = _stream_client(_always_dying, _always_dying, _always_dying)
        with patch("agent._request_executor.time.sleep"):
            with pytest.raises(httpx.ReadError):
                loop.run("task")
        assert calls["n"] == 2


def _ui_screenshot_message(obs_id: str, ref: ImageRef) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": f"[Image from read: computer_use_inspect_window {obs_id}]"},
            ref.to_content_part(),
        ],
    }


def _make_seeded_loop(tmp_path: Path, initial_messages: list[dict], **config_kwargs) -> AgentLoop:
    """Like _make_loop, but seeds history (`initial_messages`) and uses a
    real project_path so ImageAssetStore reads/writes actually land."""
    config = AgentConfig(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        project_path=tmp_path,
        **config_kwargs,
    )
    fake_registry = MagicMock()
    fake_registry.get_openai_tools_list.return_value = []
    fake_registry.list_tools.return_value = []
    fake_registry._tools = {"write_handoff": SimpleNamespace(description="submit handoff")}

    def _dispatch(name, args):
        if name == "write_handoff":
            return ToolResult(output=args.get("content", ""), side_effect=SideEffect.END_TURN)
        return "tool ran"

    fake_registry.dispatch.side_effect = _dispatch
    fake_tracker = MagicMock()
    with (
        patch("agent.loop.SessionTracker", return_value=fake_tracker),
        patch("openai.OpenAI"),
    ):
        loop = AgentLoop(
            config=config,
            _registry=fake_registry,
            tracker=fake_tracker,
            initial_messages=initial_messages,
        )
    loop.tracker = fake_tracker
    loop.registry = fake_registry
    loop._skip_slug_generation = True
    return loop


class TestRequestBuildScreenshotRetention:
    """Subtask 11: only the newest 3 UI screenshots reach the provider request,
    while the loop's own history (log / .messages) keeps all of them."""

    def test_only_newest_three_ui_screenshots_sent_to_provider(self, tmp_path: Path):
        tiny_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        store = ImageAssetStore(tmp_path)
        ref = store.store(
            ImageAttachment(data=tiny_png, mime_type="image/png", width=1, height=1, name="shot")
        )
        history = [{"role": "system", "content": "sys"}] + [
            _ui_screenshot_message(f"obs_{i}", ref) for i in range(1, 6)
        ]
        loop = _make_seeded_loop(tmp_path, history)

        # The log / .messages property must hold all 5 screenshots untouched.
        images_in_history = [
            p
            for m in loop.messages
            for p in (m.get("content") or [])
            if isinstance(p, dict) and p.get("type") == "dagi_image"
        ]
        assert len(images_in_history) == 5

        _wh_tc = SimpleNamespace(
            id="tc_end",
            function=SimpleNamespace(name="write_handoff", arguments=json.dumps({"content": "ok"})),
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=None, tool_calls=[_wh_tc], model_extra={}, reasoning_content=None,
            ))],
            usage=_usage(),
        )
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = response
        loop.run("continue")

        _, kwargs = loop.client.chat.completions.create.call_args
        sent_messages = kwargs["messages"]
        sent_image_urls = [
            p
            for m in sent_messages
            for p in (m.get("content") or [])
            if isinstance(p, dict) and p.get("type") == "image_url"
        ]
        elided_markers = [
            p["text"]
            for m in sent_messages
            for p in (m.get("content") or [])
            if isinstance(p, dict) and p.get("type") == "text" and p["text"].startswith("[screenshot")
        ]
        assert len(sent_image_urls) == 3
        assert elided_markers == ["[screenshot obs_1 elided]", "[screenshot obs_2 elided]"]

        # The loop's own history is still untouched after the request was built.
        images_in_history_after = [
            p
            for m in loop.messages
            for p in (m.get("content") or [])
            if isinstance(p, dict) and p.get("type") == "dagi_image"
        ]
        assert len(images_in_history_after) == 5
