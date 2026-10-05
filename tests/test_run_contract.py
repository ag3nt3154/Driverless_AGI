"""tests/test_run_contract.py — every way AgentLoop.run() can end leaves a well-formed log.

Safety net for moving turn/step bookkeeping out of run() (R7). Each test
drives one exit path through the real loop with a fake model, then checks:

- turns and steps open and close in order, with no step left open;
- every tool call has a result before its step ends;
- the turn ends with the expected reason;
- the events file on disk replays to the same log, and ``messages``
  matches the log's projection.
"""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from agent import session_events as sev
from agent._loop_config import CompactionResult
from agent.loop import AgentCallbacks, AgentLoop
from agent.session_log import SessionLog
from agent.session_store import append_event, read_session, write_session
from tests.test_interrupt import _WAIT, _handoff, _response, _start, _tool_call
from tests.test_streaming_loop import _make_loop

_REQ = httpx.Request("POST", "https://api.example.com/v1/chat/completions")


# ── Contract checks ──────────────────────────────────────────────────────────

def assert_well_formed(events) -> None:
    open_turn = open_step = None
    pending: set[str] = set()
    for e in events:
        if e.branch != "main":
            continue
        t, d = e.type, e.data
        where = f"seq {e.seq} {t} {dict(d)}"
        if t == sev.TURN_START:
            assert open_turn is None, f"{where}: turn {open_turn} still open"
            open_turn = d["turn"]
        elif t == sev.TURN_END:
            assert d["turn"] == open_turn, where
            assert open_step is None, f"{where}: step {open_step} still open"
            open_turn = None
        elif t == sev.STEP_START:
            assert d["turn"] == open_turn, where
            assert open_step is None, f"{where}: step {open_step} never ended"
            open_step = d["step"]
        elif t == sev.STEP_END:
            assert (d["turn"], d["step"]) == (open_turn, open_step), where
            assert not pending, f"{where}: tool calls without results: {pending}"
            open_step = None
        elif t == sev.TOOL_CALL:
            pending.add(d["call_id"])
        elif t == sev.TOOL_RESULT:
            pending.discard(d["call_id"])
    assert open_turn is None, f"turn {open_turn} left open"


def turn_end_reasons(events) -> list[str]:
    return [e.data["reason"]["kind"] for e in events if e.type == sev.TURN_END]


def assert_contract(loop: AgentLoop, events_path: Path, *reasons: str) -> None:
    events = loop.log.events
    assert_well_formed(events)
    assert turn_end_reasons(events) == list(reasons)
    on_disk = read_session(events_path)
    assert [e.seq for e in on_disk] == [e.seq for e in events]
    assert SessionLog(seed=on_disk).derive_messages() == loop.log.derive_messages()
    assert loop.messages == [loop._header_message(), *loop.log.derive_messages()]
    assert loop.is_running is False


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _loop(tmp_path: Path, responses, *, callbacks=None, **config) -> tuple[AgentLoop, Path]:
    loop = _make_loop(callbacks=callbacks, **config)
    events_path = tmp_path / "session.events.jsonl"
    write_session(events_path, loop.log.events)
    loop._events_path = events_path
    loop.log.on_append = lambda event: append_event(events_path, event)
    loop.client = MagicMock()
    loop.client.chat.completions.create.side_effect = list(responses)
    return loop, events_path


def _text(content: str):
    return _response(content=content)


def _ghost():
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=None, tool_calls=None, model_extra={}, reasoning_content=None,
        ))],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, cost=None),
    )


def _status_error(code: int):
    return openai.APIStatusError(
        message="err", response=httpx.Response(code, request=_REQ), body=None
    )


@pytest.fixture(autouse=True)
def _no_backoff():
    with patch("agent._request_executor.time.sleep"):
        yield


# ── Paths that finish inside one call ────────────────────────────────────────

def test_handoff_completes(tmp_path):
    loop, path = _loop(tmp_path, [_handoff()])
    assert loop.run("go") == "ok"
    assert_contract(loop, path, "completed")


def test_tool_step_then_handoff(tmp_path):
    loop, path = _loop(tmp_path, [
        _response(_tool_call("tc_1", "bash", {"command": "ls"})),
        _handoff(),
    ])
    loop.run("go")
    assert_contract(loop, path, "completed")


def test_text_replies_until_max_continuations(tmp_path):
    loop, path = _loop(tmp_path, [_text("thinking"), _text("still thinking")], max_continuations=1)
    assert loop.run("go") == "still thinking"
    assert_contract(loop, path, "max-continuations")


def test_two_end_turn_calls_in_one_batch(tmp_path):
    loop, path = _loop(tmp_path, [_response(
        _tool_call("tc_a", "write_handoff", {"content": "first"}),
        _tool_call("tc_b", "write_handoff", {"content": "second"}),
    )])
    loop.run("go")
    assert_contract(loop, path, "completed")


def test_null_responses_exhausted(tmp_path):
    loop, path = _loop(tmp_path, [_ghost(), _ghost()], null_response_retries=2)
    assert loop.run("go").startswith("Error: model returned a null response")
    assert_contract(loop, path, "error")


def test_non_transient_api_error(tmp_path):
    loop, path = _loop(tmp_path, [_status_error(400)])
    with pytest.raises(openai.APIStatusError):
        loop.run("go")
    assert_contract(loop, path, "error")


def test_transient_errors_exhausted_without_pause_support(tmp_path):
    loop, path = _loop(tmp_path, [_status_error(503)] * 2, api_error_retries=2)
    with pytest.raises(openai.APIStatusError):
        loop.run("go")
    assert_contract(loop, path, "error")


def test_transient_error_then_success(tmp_path):
    loop, path = _loop(tmp_path, [openai.APIConnectionError(request=_REQ), _handoff()])
    loop.run("go")
    assert_contract(loop, path, "completed")


def test_garbled_recovery_then_handoff(tmp_path):
    loop, path = _loop(tmp_path, [_text(""), _text(""), _text(""), _handoff()], max_continuations=10)
    with patch.object(loop, "compact", return_value=CompactionResult(did_compact=False)):
        loop.run("go")
    assert_contract(loop, path, "completed")
    # The empty steps are gone, but the turn and the user's task stay.
    assert {"role": "user", "content": "go"} in loop.messages


def test_reload_command(tmp_path):
    loop, path = _loop(tmp_path, [])
    with patch.object(loop, "_rebuild_for_reload", return_value=([], [], [])):
        loop.run("/reload")
    assert_contract(loop, path, "completed")


def test_consecutive_runs(tmp_path):
    loop, path = _loop(tmp_path, [_handoff(), _text("hi"), _handoff()], max_continuations=3)
    loop.run("first")
    loop.run("second")
    assert_contract(loop, path, "completed", "completed")


# ── Paths that park the loop and resume ──────────────────────────────────────

def test_pause_after_transient_errors_then_resume(tmp_path):
    callbacks = AgentCallbacks(supports_pause=True)
    loop, path = _loop(
        tmp_path, [_status_error(503)] * 2 + [_handoff()],
        callbacks=callbacks, api_error_retries=2,
    )
    thread, out = _start(loop)
    assert loop.wait_for_pause_checkpoint(timeout=_WAIT)
    loop.inject_and_resume("try again")
    thread.join(_WAIT)
    assert out.get("result") == "ok", out
    assert_contract(loop, path, "completed")


def test_interrupt_during_request_then_resume(tmp_path):
    in_request, release = threading.Event(), threading.Event()
    responses = iter([_response(content="partial"), _handoff()])

    def create(**_kwargs):
        if not in_request.is_set():
            in_request.set()
            release.wait(_WAIT)
        return next(responses)

    loop, path = _loop(tmp_path, [])
    loop.client.chat.completions.create.side_effect = create
    thread, out = _start(loop)
    assert in_request.wait(_WAIT)
    assert loop.interrupt() is True
    release.set()
    assert loop.wait_for_pause_checkpoint(timeout=_WAIT)
    loop.inject_and_resume("go on")
    thread.join(_WAIT)
    assert out.get("result") == "ok", out
    assert_contract(loop, path, "completed")


def test_garbled_recovery_after_a_real_step(tmp_path):
    loop, path = _loop(tmp_path, [
        _response(_tool_call("tc_1", "bash", {"command": "ls"})),
        _text(""), _text(""), _text(""),
        _handoff(),
    ], max_continuations=10)
    with patch.object(loop, "compact", return_value=CompactionResult(did_compact=False)):
        loop.run("go")
    assert_contract(loop, path, "completed")
    assert {"role": "user", "content": "go"} in loop.messages
