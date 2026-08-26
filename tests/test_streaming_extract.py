"""Verify the streaming consumer works from the extracted module.

Why this matters: consume_stream must reproduce exactly the (message, usage)
shapes the blocking path produces — content/reasoning accumulation, tool-call
index-based stitching, and callback firing order are all load-bearing for the
loop and session log.
"""
from types import SimpleNamespace

from agent._streaming import consume_stream


def _callbacks(**overrides):
    base = dict(
        on_stream_start=[],
        on_stream_end=[],
        on_assistant_text_delta=[],
        on_reasoning_delta=[],
    )
    cb = SimpleNamespace(
        on_stream_start=lambda: base["on_stream_start"].append("start"),
        on_stream_end=lambda: base["on_stream_end"].append("end"),
        on_assistant_text_delta=base["on_assistant_text_delta"].append,
        on_reasoning_delta=base["on_reasoning_delta"].append,
    )
    return cb, base


def _chunk(content=None, reasoning=None, tool_calls=None, usage=None):
    delta = SimpleNamespace(
        content=content,
        reasoning=reasoning,
        reasoning_content=None,
        model_extra={},
        tool_calls=tool_calls,
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


def test_consume_stream_accumulates_text_and_usage():
    cb, fired = _callbacks()
    usage = SimpleNamespace(prompt_tokens=5)
    stream = iter([
        _chunk(content="Hel"), _chunk(content="lo"), _chunk(usage=usage),
    ])
    message, got_usage = consume_stream(stream, cb)
    assert message.content == "Hello"
    assert got_usage is usage
    assert message.tool_calls is None
    assert fired["on_assistant_text_delta"] == ["Hel", "lo"]
    assert fired["on_stream_start"] == ["start"]
    assert fired["on_stream_end"] == ["end"]


def test_consume_stream_stitches_tool_calls_by_index():
    cb, _fired = _callbacks()

    def tc(index, tid="", name="", args=""):
        fn = SimpleNamespace(name=name, arguments=args) if (name or args) else None
        return SimpleNamespace(index=index, id=tid or None, function=fn)

    stream = iter([
        _chunk(tool_calls=[tc(0, tid="call_1", name="read")]),
        _chunk(tool_calls=[tc(1, tid="call_2", name="grep")]),
        _chunk(tool_calls=[tc(0, args='{"path":')])
        ,
        _chunk(tool_calls=[tc(0, args=' "x"}')]),
    ])
    message, _usage = consume_stream(stream, cb)
    assert [t.id for t in message.tool_calls] == ["call_1", "call_2"]
    assert message.tool_calls[0].function.name == "read"
    assert message.tool_calls[0].function.arguments == '{"path": "x"}'


def test_consume_stream_empty_yields_none_content():
    cb, _fired = _callbacks()
    message, usage = consume_stream(iter([]), cb)
    assert message.content is None
    assert message.tool_calls is None
    assert usage is None
