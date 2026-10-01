"""tests/test_steer.py — AgentLoop.steer(): messages typed while the agent runs.

A steered message is logged at the next checkpoint (after the current tool
results, before the next model call) without pausing the turn, and
on_user_injected confirms it. If the turn ends first it is dropped here — the
GUI resends unconfirmed messages as the next turn.
"""
from __future__ import annotations

import threading

from agent.loop import AgentCallbacks
from agent.user_input import UserSubmission
from tests.test_interrupt import _WAIT, _conversation, _handoff, _response, _start, _tool_call
from tests.test_streaming_loop import _make_loop


def _blocking_tool_loop(responses):
    """Loop whose first ``read`` call blocks until ``release`` is set."""
    tool_running, release = threading.Event(), threading.Event()
    injected: list = []
    loop = _make_loop(callbacks=AgentCallbacks(on_user_injected=injected.append))
    loop.client.chat.completions.create.side_effect = lambda **_k: responses.pop(0)
    base = loop.registry.dispatch.side_effect

    def dispatch(name, args):
        if name == "read":
            tool_running.set()
            release.wait(_WAIT)
        return base(name, args)

    loop.registry.dispatch.side_effect = dispatch
    return loop, tool_running, release, injected


def test_steered_message_lands_after_tool_results_without_pausing():
    loop, tool_running, release, injected = _blocking_tool_loop([
        _response(_tool_call("tc_a", "read", {"path": "a"})),
        _handoff(),
    ])
    requests: list[list] = []
    create = loop.client.chat.completions.create.side_effect
    loop.client.chat.completions.create.side_effect = lambda **k: (
        requests.append([dict(m) for m in k["messages"]]), create(**k))[1]
    thread, out = _start(loop)

    assert tool_running.wait(_WAIT)
    submission = UserSubmission(text="also keep the old API")
    assert loop.steer(submission) is True
    assert injected == []  # still mid-step
    release.set()
    thread.join(_WAIT)

    assert out.get("result") == "ok", out
    assert injected == [submission]
    assert loop._pause_event.is_set()  # never paused
    roles = [(m["role"], m.get("tool_call_id") or m.get("content")) for m in _conversation(loop)]
    assert roles.index(("user", "also keep the old API")) == roles.index(("tool", "tc_a")) + 1
    assert requests[1][-1] == {"role": "user", "content": "also keep the old API"}


def test_steer_is_refused_when_no_turn_runs():
    loop = _make_loop()
    assert loop.steer("hello") is False


def test_message_still_queued_when_the_turn_ends_is_not_logged():
    loop, tool_running, release, injected = _blocking_tool_loop([
        _response(_tool_call("tc_a", "read", {"path": "a"}),
                  _tool_call("tc_end", "write_handoff", {"content": "ok"})),
    ])
    thread, out = _start(loop)
    assert tool_running.wait(_WAIT)
    assert loop.steer("too late") is True
    release.set()
    thread.join(_WAIT)

    assert out.get("result") == "ok", out
    assert injected == []
    assert all(m.get("content") != "too late" for m in _conversation(loop))
    assert loop.steer("after the turn") is False


def test_cancel_steer_withdraws_before_delivery():
    loop, tool_running, release, injected = _blocking_tool_loop([
        _response(_tool_call("tc_a", "read", {"path": "a"})),
        _handoff(),
    ])
    thread, out = _start(loop)
    assert tool_running.wait(_WAIT)
    keep, drop = UserSubmission(text="keep"), UserSubmission(text="drop")
    loop.steer(keep)
    loop.steer(drop)
    assert loop.cancel_steer(drop) is True
    assert loop.cancel_steer(drop) is False
    release.set()
    thread.join(_WAIT)

    assert out.get("result") == "ok", out
    assert injected == [keep]
    contents = [m.get("content") for m in _conversation(loop)]
    assert "keep" in contents and "drop" not in contents
