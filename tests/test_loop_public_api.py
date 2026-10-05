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
from tests.test_session_log_shadow import _make_loop, _wh_response


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
    loop.tracker._path = tmp_path / "session.jsonl"
    before = len(loop.messages)
    with patch("agent.session_store.write_session") as write:
        loop.revise_last_steps(1)
    assert len(loop.messages) < before
    assert loop.messages == [loop._header_message(), *loop.log.derive_messages()]
    write.assert_called_once_with(tmp_path / "session.events.jsonl", loop.log.events)


def test_revise_last_steps_refreshes_messages_even_if_save_fails(tmp_path: Path) -> None:
    loop = _loop_after_one_turn(tmp_path)
    loop.tracker._path = tmp_path / "session.jsonl"
    before = len(loop.messages)
    with patch("agent.session_store.write_session", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            loop.revise_last_steps(1)
    assert len(loop.messages) < before
