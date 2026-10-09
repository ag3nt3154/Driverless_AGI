"""Spawn, open and close agent sessions from the Agents rail view."""
from __future__ import annotations

import uuid

from PySide6.QtCore import QObject

from pyside_gui.sidebars.agents_view import slug_error


def agent_state(session) -> str:
    """One word for an agent's dot: waiting, running, paused, error or idle."""
    if session.waiting:
        return "waiting"
    loop = session._current_loop_ref[0] if session._current_loop_ref else None
    if session.busy:
        return "paused" if loop is not None and loop.is_paused else "running"
    return session.status if session.status in ("paused", "error") else "idle"


def _slug(handle: str) -> str:
    return handle.rsplit("_", 1)[0]


class AgentsController(QObject):
    """User-only spawning: every new agent joins the board the GUI is connected to."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.view = window._left_sidebar.agents_view
        self._retired: list = []  # closed sessions a paused worker thread may still reference
        self.view.spawn_requested.connect(self.spawn)
        self.view.activate_requested.connect(self.activate)
        self.view.close_requested.connect(self.close_agent)
        window.active_session_changed.connect(lambda _session: self.refresh())
        for session in window._sessions:
            session.state_changed.connect(self.refresh)
        self.refresh()

    def _find(self, handle: str):
        return next((s for s in self.window._sessions if s.handle == handle), None)

    def spawn(self, slug: str):
        """Create ``<slug>_<uuid8>`` from the main agent's model and folder and open it."""
        from agent.config_loader import resolve_model_config

        win = self.window
        error = slug_error(slug, {_slug(s.handle) for s in win._sessions})
        if error is not None:
            self.view.show_error(error)
            return None
        base = win._main
        try:
            config = resolve_model_config(base._config.model_id or None,
                                          project_path=base._project_path)
        except Exception as exc:  # a broken model config must not take the window down
            self.view.show_error(f"Cannot spawn {slug}: {exc}")
            return None
        handle = f"{slug}_{uuid.uuid4().hex[:8]}"
        session = win.add_session(config, base._project_path, handle)
        session.state_changed.connect(self.refresh)
        session._board_session = win._board_controller.add_session(handle)
        session.show_welcome()
        self.view.show_error(None)
        win._activate(session)
        return session

    def activate(self, handle: str) -> None:
        session = self._find(handle)
        if session is not None and session is not self.window._active:
            self.window._activate(session)

    def close_agent(self, handle: str) -> None:
        """Stop a spawned agent's turn and remove it; the main agent cannot be closed."""
        win = self.window
        session = self._find(handle)
        if session is None or session is win._main:
            return
        if session.waiting:
            self.view.show_error(f"{handle} is waiting for an answer — answer it first.")
            return
        if agent_state(session) == "running":
            session.stop()
        win.remove_session(session)
        win._board_controller.remove_session(session._board_session)
        self._retired.append(session)
        self.view.show_error(None)
        self.refresh()

    def on_board_ready(self) -> None:
        """The board connected: adopt the main handle and give earlier agents board tools."""
        win = self.window
        controller = win._board_controller
        if controller.sessions:
            win._main.handle = controller.sessions[0].handle
        for session in win._sessions[1:]:
            if session._board_session is None:
                session._board_session = controller.add_session(session.handle)
        self.refresh()

    def refresh(self, *_args) -> None:
        win = self.window
        self.view.set_agents([
            {"handle": s.handle, "slug": _slug(s.handle), "state": agent_state(s),
             "folder": s._project_path, "active": s is win._active, "main": s is win._main}
            for s in win._sessions
        ])
        if len(win._sessions) > 1:
            win._refresh_title()
