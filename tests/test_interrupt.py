"""tests/test_interrupt.py — AgentLoop.interrupt(): Esc stops the step in flight.

An interrupted stream stops at once and keeps its partial text; a blocking
response that lands after the interrupt is dropped; tools of an interrupted
batch never run; and a message sent right after Esc is logged only once the
loop has parked, never between a tool call and its result.
"""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import httpx

from agent._streaming import consume_stream
from agent.loop import AgentCallbacks
from tests.test_streaming_loop import _chunk, _make_loop, _stream_client, _usage, _wh_chunks

_WAIT = 5.0


def _tool_call(call_id: str, name: str, args: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id, type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _response(*tool_calls, content=None) -> SimpleNamespace:
    message = SimpleNamespace(
        content=content, tool_calls=list(tool_calls) or None,
        model_extra={}, reasoning_content=None,
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=_usage())


def _handoff() -> SimpleNamespace:
    return _response(_tool_call("tc_end", "write_handoff", {"content": "ok"}))


class _HangingStream:
    """Yields ``chunks`` then blocks like a slow provider until close()."""

    def __init__(self, chunks):
        self._chunks = chunks
        self._closed = threading.Event()
        self.closed_at: float | None = None

    def __iter__(self):
        yield from self._chunks
        self._closed.wait(_WAIT)
        raise httpx.ReadError("stream closed")

    def close(self):
        self.closed_at = time.monotonic()
        self._closed.set()


def _start(loop, task="do it"):
    out: dict = {}

    def target():
        try:
            out["result"] = loop.run(task)
        except Exception as exc:  # pragma: no cover - surfaced by the asserts
            out["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, out


def _conversation(loop) -> list[dict]:
    return [m for m in loop._messages if m.get("role") in ("user", "assistant", "tool")]


def test_interrupt_closes_the_stream_and_keeps_only_partial_text():
    first_delta = threading.Event()
    loop = _make_loop(
        callbacks=AgentCallbacks(on_assistant_text_delta=lambda _t: first_delta.set()),
        stream=True,
    )
    hanging = _HangingStream([
        _chunk(content="Partial answer "),
        _chunk(tool_calls=[SimpleNamespace(
            index=0, id="tc_bash",
            function=SimpleNamespace(name="bash", arguments='{"comm'),
        )]),
    ])
    loop.client, _calls = _stream_client(lambda: hanging, _wh_chunks("ok"))
    thread, out = _start(loop)

    assert first_delta.wait(_WAIT)
    started = time.monotonic()
    assert loop.interrupt() is True
    assert loop.wait_for_pause_checkpoint(timeout=_WAIT)
    assert time.monotonic() - started < 1.0
    assert hanging.closed_at is not None
    assert loop.interrupt() is False  # already paused

    assert _conversation(loop)[-1] == {"role": "assistant", "content": "Partial answer"}
    loop.registry.dispatch.assert_not_called()

    loop.inject_and_resume("go on")
    thread.join(_WAIT)
    assert out.get("result") == "ok", out
    tail = _conversation(loop)
    assert tail[1] == {"role": "assistant", "content": "Partial answer"}
    assert tail[2] == {"role": "user", "content": "go on"}


def test_blocking_response_after_interrupt_is_dropped_even_after_a_quick_resume():
    in_request, release = threading.Event(), threading.Event()
    responses = [
        _response(_tool_call("tc_bash", "bash", {"command": "rm -rf build"}), content="Cleaning"),
        _handoff(),
    ]

    def create(**_kwargs):
        if len(responses) == 2:
            in_request.set()
            release.wait(_WAIT)
        return responses.pop(0)

    loop = _make_loop()
    loop.client.chat.completions.create.side_effect = create
    thread, out = _start(loop)

    assert in_request.wait(_WAIT)
    assert loop.interrupt() is True
    loop.inject_and_resume("actually, stop that")  # before the loop noticed
    release.set()
    thread.join(_WAIT)

    assert out.get("result") == "ok", out
    dispatched = [c.args[0] for c in loop.registry.dispatch.call_args_list]
    assert dispatched == ["write_handoff"]
    conversation = _conversation(loop)
    assert all("Cleaning" not in str(m.get("content")) for m in conversation)
    assert conversation[1] == {"role": "user", "content": "actually, stop that"}


def test_interrupt_mid_batch_cancels_the_rest_and_queues_the_message_after_results():
    tool_running, release = threading.Event(), threading.Event()
    responses = [
        _response(
            _tool_call("tc_a", "read", {"path": "a"}),
            _tool_call("tc_b", "read", {"path": "b"}),
        ),
        _handoff(),
    ]
    loop = _make_loop()
    loop.client.chat.completions.create.side_effect = lambda **_k: responses.pop(0)
    dispatched: list[str] = []
    base = loop.registry.dispatch.side_effect

    def dispatch(name, args):
        dispatched.append(f"{name}:{args.get('path', '')}")
        if args.get("path") == "a":
            tool_running.set()
            release.wait(_WAIT)
        return base(name, args)

    loop.registry.dispatch.side_effect = dispatch
    thread, out = _start(loop)

    assert tool_running.wait(_WAIT)
    assert loop.interrupt() is True
    loop.inject_and_resume("change of plan")  # arrives while tool a still runs
    release.set()
    thread.join(_WAIT)

    assert out.get("result") == "ok", out
    assert dispatched == ["read:a", "write_handoff:"]
    roles = [(m["role"], m.get("tool_call_id") or m.get("content")) for m in _conversation(loop)]
    user_at = roles.index(("user", "change of plan"))
    assert roles[user_at - 2:user_at] == [("tool", "tc_a"), ("tool", "tc_b")]


def test_consume_stream_stops_on_abort_and_swallows_the_close_error():
    abort = threading.Event()
    seen: list[str] = []

    def chunks():
        yield _chunk(content="one ")
        abort.set()
        raise httpx.ReadError("closed by interrupt")

    message, _usage_ = consume_stream(chunks(), AgentCallbacks(on_assistant_text_delta=seen.append), abort)
    assert message.content == "one "
    assert message.tool_calls is None
    assert seen == ["one "]


def test_interrupt_kills_bash_then_a_running_code_script():
    from unittest.mock import MagicMock, call
    loop = _make_loop()
    order = MagicMock()
    loop.registry._tools.update({"bash": order.bash, "code": order.code})

    assert loop.interrupt() is True
    assert order.mock_calls[:2] == [call.bash.force_kill(), call.code.force_kill()]
