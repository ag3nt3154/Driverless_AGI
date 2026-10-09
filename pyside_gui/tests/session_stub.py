"""A lightweight AgentSession for tests: real slots and properties, stub window chrome."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import QObject

from pyside_gui.agent_session import AgentSession


def stub_window(**overrides) -> SimpleNamespace:
    window = SimpleNamespace(
        _active=None, _prompt=MagicMock(), _right_sidebar=MagicMock(),
        _left_sidebar=MagicMock(), _apply_running=MagicMock(), _compose_mode=False,
        _toggle_compose=MagicMock(), close=MagicMock(), _on_active_config_changed=MagicMock(),
        isActiveWindow=MagicMock(return_value=True),
    )
    for name, value in overrides.items():
        setattr(window, name, value)
    return window


class StubSession(AgentSession):
    """AgentSession without widgets; assign fakes for what a test touches."""

    def __init__(self, win=None, *, active: bool = True, handle: str = "main_12345678") -> None:
        QObject.__init__(self)
        self.win = win if win is not None else stub_window()
        if active:
            self.win._active = self
        self.handle = handle
        self._config = SimpleNamespace(display_name="test", project_path=None)
        self._project_path = None
        self._active_loop = None
        self._worker = None
        self._current_loop_ref = []
        self._run_start_time = None
        self._restore_initial_messages = None
        self._restore_initial_affect = None
        self._pending_ask = None
        self._pending_ask_container = None
        self._stream_had_content = False
        self._stream_had_reasoning = False
        self._streaming_active = False
        self._submission_seq = 0
        self._board_session = None
        self.status = "idle"
        self.running = False
        self._last_tokens = None
        self._last_context = None
        self._model_name = "test"
        self._bridge = MagicMock()
        self._conversation = MagicMock()
        self._cmd_handler = MagicMock()
        self._copy_picker = MagicMock()
