"""Agents rail view: spawning, switching, closing, board binding and background turns."""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal

from pyside_gui.agents_controller import AgentsController, agent_state
from pyside_gui.sidebars.agents_view import AgentsView, slug_error
from pyside_gui.tests.session_stub import StubSession, stub_window


class FakeBoard:
    def __init__(self, handle="main_11112222"):
        self.sessions = [SimpleNamespace(handle=handle)]
        self.added, self.removed = [], []

    def add_session(self, handle):
        session = SimpleNamespace(handle=handle)
        self.added.append(handle)
        self.sessions.append(session)
        return session

    def remove_session(self, session):
        self.removed.append(session)


class FakeWindow(QObject):
    active_session_changed = Signal(object)

    def __init__(self, qtbot):
        super().__init__()
        view = AgentsView()
        qtbot.addWidget(view)
        self._left_sidebar = SimpleNamespace(agents_view=view)
        self._board_controller = FakeBoard()
        self._sessions = []
        self._active = None
        self.chrome = stub_window(_active=None)
        main = self.add_session(None, Path("C:/work"), "main")
        self._activate(main)
        self.titles = 0

    @property
    def _main(self):
        return self._sessions[0]

    def add_session(self, config, project_path, handle):
        session = StubSession(self.chrome, active=False, handle=handle)
        session._project_path = project_path
        session._config = SimpleNamespace(model_id="m", display_name="M", project_path=None)
        session.show_welcome = MagicMock()
        self._sessions.append(session)
        return session

    def _activate(self, session):
        self._active = self.chrome._active = session
        self.active_session_changed.emit(session)

    def remove_session(self, session):
        if session is self._active:
            self._activate(self._main)
        self._sessions.remove(session)

    def _refresh_title(self):
        self.titles += 1


@pytest.fixture
def setup(qtbot, monkeypatch):
    monkeypatch.setattr("agent.config_loader.resolve_model_config",
                        lambda model, project_path=None: SimpleNamespace(
                            model_id=model, display_name="M", project_path=project_path))
    window = FakeWindow(qtbot)
    return window, AgentsController(window)


def _rows(view):
    return [view._list.item(i).text() for i in range(view._list.count())]


def test_slug_rules():
    assert slug_error("researcher", set()) is None
    assert slug_error("a-1", set()) is None
    for bad in ("", "Bad", "-x", "x" * 33, "a_b", "a b"):
        assert slug_error(bad, set()), bad
    assert "reserved" in slug_error("main", set())
    assert "already exists" in slug_error("dup", {"dup"})


def test_spawn_two_agents_with_distinct_handles_on_the_board(setup):
    window, controller = setup
    first = controller.spawn("researcher")
    second = controller.spawn("coder")
    assert first.handle.startswith("researcher_") and len(first.handle) == len("researcher_") + 8
    assert second.handle.startswith("coder_") and first.handle != second.handle
    assert window._board_controller.added == [first.handle, second.handle]
    assert first._board_session.handle == first.handle
    assert first._project_path == window._main._project_path
    assert window._active is second
    first.show_welcome.assert_called_once()
    rows = _rows(window._left_sidebar.agents_view)
    assert len(rows) == 3 and rows[2].startswith("▶") and second.handle in rows[2]


def test_invalid_or_duplicate_slug_spawns_nothing(setup):
    window, controller = setup
    controller.spawn("helper")
    view = window._left_sidebar.agents_view
    view._slug.setText("helper")
    view._spawn()
    assert "already exists" in view._error.text() and not view._error.isHidden()
    assert controller.spawn("Bad Slug") is None
    assert len(window._sessions) == 2


def test_clicking_a_row_opens_that_agent(setup):
    window, controller = setup
    helper = controller.spawn("helper")
    view = window._left_sidebar.agents_view
    view._on_clicked(view._list.item(0))
    assert window._active is window._main
    view._on_clicked(view._list.item(1))
    assert window._active is helper


def test_close_stops_a_running_agent_and_keeps_its_objects(setup):
    window, controller = setup
    helper = controller.spawn("helper")
    loop = SimpleNamespace(is_paused=False)
    helper._worker = SimpleNamespace(is_alive=lambda: True)
    helper._current_loop_ref = [loop]
    helper.stop = MagicMock(return_value=True)
    controller.close_agent(helper.handle)
    helper.stop.assert_called_once()
    assert helper not in window._sessions and window._active is window._main
    assert window._board_controller.removed == [helper._board_session]
    assert controller._retired == [helper]
    controller.close_agent(window._main.handle)
    assert window._main in window._sessions


def test_waiting_agent_is_not_closed(setup):
    window, controller = setup
    helper = controller.spawn("helper")
    helper._pending_ask = object()
    controller.close_agent(helper.handle)
    assert helper in window._sessions
    assert "waiting for an answer" in window._left_sidebar.agents_view._error.text()


def test_agent_state_words():
    session = StubSession()
    assert agent_state(session) == "idle"
    session._worker = SimpleNamespace(is_alive=lambda: True)
    session._current_loop_ref = [SimpleNamespace(is_paused=False)]
    assert agent_state(session) == "running"
    session._current_loop_ref[0].is_paused = True
    assert agent_state(session) == "paused"
    session._pending_ask = object()
    assert agent_state(session) == "waiting"


def test_board_ready_adopts_main_handle_and_binds_earlier_agents(setup):
    window, controller = setup
    window._board_controller.add_session = MagicMock(return_value=None)
    helper = controller.spawn("helper")  # spawned while the board was offline
    assert helper._board_session is None
    board = FakeBoard("main_aaaabbbb")
    window._board_controller = board
    controller.on_board_ready()
    assert window._main.handle == "main_aaaabbbb"
    assert board.added == [helper.handle] and helper._board_session.handle == helper.handle


def test_real_window_routes_prompt_to_active_agent_and_streams_background_turn(
    qtbot, monkeypatch, tmp_path,
):
    """A7: a turn in a hidden agent renders into its own view; the prompt follows the active one."""
    from pyside_gui import _dispatch
    from pyside_gui.app import DagiMainWindow
    from pyside_gui.board_controller import BoardController
    from pyside_gui.conversation import ConversationView

    monkeypatch.setattr(BoardController, "start", lambda self: None)
    seen = []
    monkeypatch.setattr(ConversationView, "append_assistant",
                        lambda self, text: seen.append((self, text)))

    class FakeLoop:
        def __init__(self, config, callbacks, **_kwargs):
            self.callbacks, self.config = callbacks, config
            self.messages, self.tracker, self.log, self.is_paused = [], None, None, False

        def run(self, task):
            time.sleep(0.2)
            self.callbacks.on_assistant_text(f"echo: {task.text}")
            self.callbacks.on_done("")

        def finish(self):
            pass

    monkeypatch.setattr(_dispatch, "AgentLoop", FakeLoop)
    from agent.config_loader import resolve_model_config

    config = resolve_model_config(None, project_path=tmp_path)
    window = DagiMainWindow(config, tmp_path, verbose=False)
    qtbot.addWidget(window)
    main = window._active
    helper = window._agents.spawn("helper")
    assert window._active is helper
    assert window._left_sidebar.agents_view._list.count() == 2
    window._on_input_submitted("hello")
    assert helper.busy and not main.busy
    window._agents.activate(main.handle)
    assert window._conversation_stack.currentWidget() is main._conversation
    # The reply is a queued signal: wait for it, not for the worker thread to exit.
    qtbot.waitUntil(lambda: bool(seen), timeout=10000)
    assert seen == [(helper._conversation, "echo: hello")]
    qtbot.waitUntil(lambda: not helper.busy, timeout=10000)
    window.close()


def test_agents_is_the_sixth_rail_view():
    from pyside_gui.left_sidebar import _RAIL_TIPS, _VIEW_NAMES

    assert _VIEW_NAMES[:5] == ("history", "files", "viewer", "plan", "board")
    assert _VIEW_NAMES[5] == "agents" and _RAIL_TIPS[5] == "Agents"
