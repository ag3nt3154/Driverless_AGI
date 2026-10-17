"""Peer turn-end reporting and close_on_done (Subtask 7, D4/D5/D12; ESC D14)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.board_client import BoardError
from pyside_gui import agent_session
from pyside_gui.peers import report_post
from pyside_gui.tests.session_stub import StubSession, stub_window


class FakeBoard:
    """Records ``post`` calls; reads attachment contents at call time."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.fail = fail

    def post(self, text: str, files=()) -> dict:
        contents = [Path(f).read_text(encoding="utf-8") for f in files]
        self.calls.append((text, contents))
        if self.fail:
            raise BoardError("FAIL", "boom")
        return {"id": len(self.calls)}


def _peer(tmp_path, monkeypatch, *, close_on_done: bool = False, fail: bool = False):
    monkeypatch.setattr(agent_session, "DAGI_ROOT", tmp_path)
    s = StubSession(handle="fixer_1234abcd")
    s.spawned_by = "main_11112222"
    s.close_on_done = close_on_done
    board = FakeBoard(fail=fail)
    s._board_session = board
    s.win._board_controller = SimpleNamespace(_run_worker=lambda target, name: target())
    s.win._agents = SimpleNamespace(close_agent=MagicMock())
    return s, board


def test_handoff_turn_posts_done_with_full_handoff_attached(qtbot, tmp_path, monkeypatch):
    s, board = _peer(tmp_path, monkeypatch)
    handoff = "y" * 3000

    s._show_running()
    s._on_turn_handoff(handoff)
    s._on_agent_done(handoff)
    s._turn_finished_slot()

    assert len(board.calls) == 1
    text, contents = board.calls[0]
    assert text == report_post("main_11112222", "done", handoff)
    assert contents == [handoff]
    assert s.last_outcome == "done"


@pytest.mark.parametrize("outcome", ["done", "max-continuations", "error"])
def test_close_on_done_closes_only_after_clean_done(qtbot, tmp_path, monkeypatch, outcome):
    s, board = _peer(tmp_path, monkeypatch, close_on_done=True)

    s._show_running()
    if outcome == "done":
        s._on_turn_handoff("the handoff")
        s._on_agent_done("the handoff")
    elif outcome == "max-continuations":
        s._on_agent_done("")
    else:
        s._on_turn_error("boom")
    s._turn_finished_slot()

    if outcome == "done":
        qtbot.waitUntil(lambda: s.win._agents.close_agent.called, timeout=2000)
    else:
        qtbot.wait(100)
        assert not s.win._agents.close_agent.called
    assert s.last_outcome == outcome


def test_max_continuations_and_error_tags(qtbot, tmp_path, monkeypatch):
    s, board = _peer(tmp_path, monkeypatch)

    s._show_running()
    s._on_agent_done("")
    s._turn_finished_slot()
    assert board.calls[-1][0].startswith("@main_11112222 [max-continuations]")

    s._show_running()
    s._on_assistant_text("last words")
    s._on_turn_error("boom")
    s._turn_finished_slot()
    assert "last words" in board.calls[-1][0]

    s._show_running()
    s._on_turn_error("boom2")
    s._turn_finished_slot()
    assert "boom2" in board.calls[-1][0]


def test_esc_on_peer_posts_nothing_and_keeps_it(qtbot, tmp_path, monkeypatch):
    s, board = _peer(tmp_path, monkeypatch, close_on_done=True)
    loop = MagicMock()
    loop.interrupt.return_value = True
    s._worker = SimpleNamespace(is_alive=lambda: True)
    s._current_loop_ref = [loop]
    s._pending_ask = None
    s._streaming_active = False
    s._enable_input = MagicMock()

    s._show_running()
    s._on_turn_handoff("would-be handoff")
    assert s.stop() is True

    qtbot.wait(100)
    assert board.calls == []
    assert s.last_outcome is None
    assert not s.win._agents.close_agent.called


def test_user_spawned_agent_never_reports(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(agent_session, "DAGI_ROOT", tmp_path)
    s = StubSession(handle="fixer_1234abcd")
    assert s.spawned_by is None
    board = FakeBoard()
    s._board_session = board
    s.win._board_controller = SimpleNamespace(_run_worker=lambda target, name: target())
    s.win._agents = SimpleNamespace(close_agent=MagicMock())

    s._show_running()
    s._on_turn_handoff("a handoff")
    s._on_agent_done("a handoff")
    s._turn_finished_slot()

    assert board.calls == []
    assert s.last_outcome is None


def test_report_post_failure_keeps_peer_and_shows_error(qtbot, tmp_path, monkeypatch):
    s, board = _peer(tmp_path, monkeypatch, fail=True)

    s._show_running()
    s._on_turn_handoff("the handoff")
    s._on_agent_done("the handoff")
    s._turn_finished_slot()

    qtbot.waitUntil(lambda: s._conversation.append_error.called, timeout=2000)
    text = s._conversation.append_error.call_args[0][0]
    assert "Could not report to main_11112222" in text
    assert not s.win._agents.close_agent.called


def test_newer_turn_cancels_a_pending_close_on_done(qtbot, tmp_path, monkeypatch):
    s, board = _peer(tmp_path, monkeypatch, close_on_done=True)

    s._show_running()
    s._on_turn_handoff("the handoff")
    s._on_agent_done("the handoff")
    s._turn_finished_slot()  # queues the close
    s._submission_seq += 1   # a mention started a new turn before the close ran ...
    s.last_outcome = "error"  # ... and that turn failed: D5 keeps the peer open
    qtbot.wait(100)

    assert len(board.calls) == 1
    assert not s.win._agents.close_agent.called


def test_handoff_file_write_failure_is_reported_and_peer_kept(qtbot, tmp_path, monkeypatch):
    s, board = _peer(tmp_path, monkeypatch, close_on_done=True)
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    monkeypatch.setattr(agent_session, "DAGI_ROOT", blocker)  # mkdir under a file fails

    s._show_running()
    s._on_turn_handoff("the handoff")
    s._on_agent_done("the handoff")
    s._turn_finished_slot()

    qtbot.waitUntil(lambda: s._conversation.append_error.called, timeout=2000)
    assert "Could not report to main_11112222" in s._conversation.append_error.call_args[0][0]
    assert board.calls == [] and s.last_outcome == "unreported"
    qtbot.wait(100)
    assert not s.win._agents.close_agent.called


def test_server_error_pause_posts_error(qtbot, tmp_path, monkeypatch):
    s, board = _peer(tmp_path, monkeypatch)

    s._show_running()
    s._on_agent_paused()

    assert len(board.calls) == 1
    assert board.calls[0][0].startswith("@main_11112222 [error] paused after a server error")
    assert s.last_outcome == "error"


def _busy(session) -> None:
    """Make ``session.stop()`` proceed: a running worker with an interruptible loop."""
    loop = MagicMock()
    loop.interrupt.return_value = True
    loop.is_paused = False
    session._worker = SimpleNamespace(is_alive=lambda: True)
    session._current_loop_ref = [loop]
    session._pending_ask = None
    session._streaming_active = False
    session._enable_input = MagicMock()


def _peer_view(handle, *, spawned_by, running=False, waiting=False):
    s = StubSession(win=stub_window(), handle=handle)
    s.spawned_by = spawned_by
    if waiting:
        s._pending_ask = object()
    elif running:
        loop = MagicMock()
        loop.is_paused = False
        s._worker = SimpleNamespace(is_alive=lambda: True)
        s._current_loop_ref = [loop]
    return s


def test_esc_on_main_lists_active_peers_only(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(agent_session, "DAGI_ROOT", tmp_path)
    main = StubSession(handle="main_11112222")
    main._board_session = SimpleNamespace(handle="main_11112222")
    _busy(main)

    p_running = _peer_view("fixer_aaaa1111", spawned_by="main_11112222", running=True)
    p_waiting = _peer_view("docs_bbbb2222", spawned_by="main_11112222", waiting=True)
    p_idle = _peer_view("idle_cccc3333", spawned_by="main_11112222")
    p_user = _peer_view("user_dddd4444", spawned_by=None, running=True)

    main.win._main = main
    main.win._sessions = [main, p_running, p_waiting, p_idle, p_user]

    assert main.stop() is True

    main._conversation.append_info.assert_any_call(
        "⏹ Stopped. Peers still active: fixer_aaaa1111 (running), "
        "docs_bbbb2222 (waiting for you). See the Agents view."
    )
    for peer in (p_running, p_waiting, p_idle, p_user):
        assert not peer._current_loop_ref or not peer._current_loop_ref[0].interrupt.called


def test_esc_on_main_without_active_peers_adds_nothing(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(agent_session, "DAGI_ROOT", tmp_path)
    main = StubSession(handle="main_11112222")
    main._board_session = SimpleNamespace(handle="main_11112222")
    _busy(main)

    p_idle = _peer_view("idle_cccc3333", spawned_by="main_11112222")

    main.win._main = main
    main.win._sessions = [main, p_idle]

    assert main.stop() is True

    main._conversation.append_info.assert_called_once_with(
        "Interrupted — type a message to continue"
    )


def test_esc_on_a_peer_shows_no_notice(qtbot, tmp_path, monkeypatch):
    s, board = _peer(tmp_path, monkeypatch)
    _busy(s)
    main = StubSession(win=s.win, handle="main_11112222")
    s.win._main = main
    s.win._sessions = [main, s]

    assert s.stop() is True

    s._conversation.append_info.assert_called_once_with(
        "Interrupted — type a message to continue"
    )


def test_bridge_handoff_reaches_session(qtbot, tmp_path, monkeypatch):
    from pyside_gui.bridge import AgentBridge

    monkeypatch.setattr(agent_session, "DAGI_ROOT", tmp_path)
    s = StubSession(handle="fixer_1234abcd")
    s.win._on_notepad_flush_requested = MagicMock()
    bridge = AgentBridge()
    s._bridge = bridge
    s._connect_signals()

    callbacks = bridge.build_callbacks()
    callbacks.on_handoff()
    callbacks.on_tool_end("write_handoff", "r")
    callbacks.on_done("r")
    qtbot.wait(50)

    assert s._turn_handoff == "r"
    assert s._turn_done_seen is True
