"""tests/test_loop_public_api.py — the AgentLoop surface frontends rely on.

Frontends (GUI, TUI, Telegram, scheduler, subagent runner) must use these
instead of private loop state.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.loop import AgentLoop
from agent.session_log import SessionLog
from agent.session_store import append_event, read_session, write_session
from agent._loop_config import CompactionResult
from tests.test_session_log_shadow import _make_loop, _text_response, _wh_response


def _loop_after_one_turn(tmp_path: Path) -> AgentLoop:
    loop = _make_loop(tmp_path)
    loop.client = MagicMock()
    loop.client.chat.completions.create.return_value = _wh_response("ok")
    loop.run("hello")
    return loop


def test_constructor_takes_public_tracker_and_session_log() -> None:
    # scheduler/runner.py passes tracker=; it must not be a TypeError.
    params = inspect.signature(AgentLoop.__init__).parameters
    assert "tracker" in params and "session_log" in params
    assert "_tracker" not in params and "_session_log" not in params


def test_messages_is_a_copy(tmp_path: Path) -> None:
    loop = _loop_after_one_turn(tmp_path)
    msgs = loop.messages
    assert msgs == loop._messages and msgs is not loop._messages
    msgs.clear()
    assert loop.messages  # caller cannot mutate loop state


def test_is_paused_tracks_pause(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    assert loop.is_paused is False
    loop.pause()
    assert loop.is_paused is True


def test_is_running_only_during_run(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    seen: list[bool] = []
    loop.callbacks.on_iteration = lambda _i: seen.append(loop.is_running)
    loop.client = MagicMock()
    loop.client.chat.completions.create.return_value = _wh_response("ok")
    assert loop.is_running is False
    loop.run("hello")
    assert seen == [True]
    assert loop.is_running is False


def test_revise_last_steps_refreshes_messages_and_persists(tmp_path: Path) -> None:
    loop = _loop_after_one_turn(tmp_path)
    loop._events_path = tmp_path / "session.events.jsonl"
    before = len(loop.messages)
    with patch("agent.session_store.write_session") as write:
        loop.revise_last_steps(1)
    assert len(loop.messages) < before
    assert loop.messages == [loop._header_message(), *loop.log.derive_messages()]
    write.assert_called_once_with(tmp_path / "session.events.jsonl", loop.log.events)


def test_revise_last_steps_refreshes_messages_even_if_save_fails(tmp_path: Path) -> None:
    loop = _loop_after_one_turn(tmp_path)
    loop._events_path = tmp_path / "session.events.jsonl"
    before = len(loop.messages)
    with patch("agent.session_store.write_session", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            loop.revise_last_steps(1)
    assert len(loop.messages) < before


def test_revise_last_steps_stops_when_no_steps_left(tmp_path: Path) -> None:
    loop = _loop_after_one_turn(tmp_path)
    with patch("agent.session_store.write_session"):
        assert loop.revise_last_steps(5) == 1
        assert loop.revise_last_steps(1) == 0


def test_revise_last_steps_writes_the_file_appends_go_to(tmp_path: Path) -> None:
    # The tracker renames its own file when it gets a slug; the events file must not move.
    loop = _loop_after_one_turn(tmp_path)
    loop._events_path = tmp_path / "session.events.jsonl"
    loop.tracker._path = tmp_path / "renamed_logs.jsonl"
    with patch("agent.session_store.write_session") as write:
        loop.revise_last_steps(1)
    assert write.call_args.args[0] == tmp_path / "session.events.jsonl"


def _wire_events_file(loop: AgentLoop, path: Path) -> None:
    write_session(path, loop.log.events)
    loop._events_path = path
    loop.log.on_append = lambda event: append_event(path, event)


def test_garbled_recovery_is_saved_to_the_events_file(tmp_path: Path) -> None:
    """R6: the file must replay to the same log the live loop holds."""
    loop = _make_loop(tmp_path, max_continuations=10)
    events_path = tmp_path / "session.events.jsonl"
    _wire_events_file(loop, events_path)
    loop.client = MagicMock()
    loop.client.chat.completions.create.side_effect = [
        _text_response(""), _text_response(""), _text_response(""),  # garbled
        _wh_response("recovered"),
    ]
    with patch.object(loop, "compact", return_value=CompactionResult(did_compact=False)) as compact:
        loop.run("do something")
    compact.assert_called_once_with(summarize_all=True)

    on_disk = read_session(events_path)
    assert [e.seq for e in on_disk] == [e.seq for e in loop.log.events]
    assert SessionLog(seed=on_disk).derive_messages() == loop.log.derive_messages()
    assert not [
        m for m in loop.messages
        if m.get("role") == "assistant" and not (m.get("content") or "").strip()
        and not m.get("tool_calls")
    ]
