from __future__ import annotations

import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import pyside_gui  # noqa: F401 — must be imported before any PySide6 import

from PySide6.QtWidgets import QApplication

from agent.expression import ExpressionSnapshot
from agent.expression_assets import TextFallback
from agent.process_state import ProcessSnapshot
from pyside_gui.bridge import AgentBridge

# PySide6 requires a QApplication to exist for QObject/Signal to work.
# Create one at module level for the test session.
_app = QApplication.instance() or QApplication(sys.argv)


def test_start_timers_does_not_require_removed_affect_config(monkeypatch):
    from pyside_gui.app import DagiMainWindow

    timer = MagicMock()
    monkeypatch.setattr("pyside_gui.app.QTimer", MagicMock(return_value=timer))
    window = DagiMainWindow.__new__(DagiMainWindow)
    window._tick_spinner = MagicMock()
    window._poll_plan = MagicMock()

    DagiMainWindow._start_timers(window)

    assert timer.start.call_count == 2


def test_tool_started_signal_emits():
    bridge = AgentBridge()
    received = []
    bridge.tool_started.connect(lambda n, a: received.append((n, a)))
    callbacks = bridge.build_callbacks()
    callbacks.on_tool_start("bash", "run ls", '{"command": "ls"}')
    _app.processEvents()
    assert len(received) == 1
    assert received[0] == ("bash", '{"command": "ls"}')


def test_build_callbacks_passes_board_session():
    bridge = AgentBridge()
    board = object()
    assert bridge.build_callbacks(board=board).board is board


def test_assistant_text_emits_raw_markdown():
    """The conversation page renders markdown itself (Vditor), so the bridge
    passes the model's text through untouched."""
    bridge = AgentBridge()
    received = []
    bridge.assistant_text.connect(lambda h: received.append(h))
    callbacks = bridge.build_callbacks()
    callbacks.on_assistant_text("**bold**")
    _app.processEvents()
    assert received == ["**bold**"]


def test_stream_deltas_emit():
    bridge = AgentBridge()
    text_chunks = []
    reason_chunks = []
    bridge.stream_text_delta.connect(lambda c: text_chunks.append(c))
    bridge.stream_reasoning_delta.connect(
        lambda c: reason_chunks.append(c)
    )
    callbacks = bridge.build_callbacks()
    callbacks.on_stream_start()
    callbacks.on_assistant_text_delta("hello ")
    callbacks.on_assistant_text_delta("world")
    callbacks.on_reasoning_delta("thinking...")
    _app.processEvents()
    assert text_chunks == ["hello ", "world"]
    assert reason_chunks == ["thinking..."]


def test_agent_done_emits():
    bridge = AgentBridge()
    received = []
    bridge.agent_done.connect(lambda r: received.append(r))
    callbacks = bridge.build_callbacks()
    callbacks.on_done("result text")
    _app.processEvents()
    assert received == ["result text"]


def test_stale_pending_ask_cleared_on_agent_done():
    """A timed-out ask_user must not swallow the next user message."""
    from pyside_gui.tests.session_stub import StubSession

    app = StubSession()
    bridge = AgentBridge()
    app._bridge = bridge
    # Notifications are not this test's target — stub them out.
    app._notify = MagicMock()

    stale_event = threading.Event()
    app._pending_ask = stale_event
    app._pending_ask_container = ["old"]

    bridge.agent_done.connect(app._on_agent_done)
    bridge.agent_done.emit("done")
    _app.processEvents()

    assert app._pending_ask is None
    assert app._pending_ask_container is None


def test_token_update_accumulates():
    bridge = AgentBridge()
    received = []
    bridge.token_update.connect(
        lambda i, o, c, t, ca: received.append((i, o, c, t, ca))
    )
    callbacks = bridge.build_callbacks()
    callbacks.on_token_update(100, 50, 0.01, 20, 10)
    callbacks.on_token_update(200, 80, 0.02, 30, 15)
    _app.processEvents()
    assert len(received) == 2
    # Stats accumulates — second emission should show totals
    assert received[1][0] == 300  # input
    assert received[1][1] == 130  # output


def test_process_snapshot_emits_as_object_and_expression_is_ignored(tmp_path) -> None:
    bridge = AgentBridge()
    received = []
    bridge.process_state_changed.connect(lambda s: received.append(s))
    callbacks = bridge.build_callbacks()
    asset = TextFallback(tmp_path / "default.md", "test", "fallback")
    process = ProcessSnapshot("thinking", asset)

    # The GUI renders only the process channel; expression updates are a no-op.
    callbacks.on_expression_changed(ExpressionSnapshot("focused", asset))
    callbacks.on_process_state_changed(process)
    _app.processEvents()

    assert not hasattr(bridge, "expression_changed")
    assert received == [process]


def test_handoff_text_emits_on_done():
    """write_handoff content should emit via handoff_text, not assistant_text."""
    bridge = AgentBridge()
    assistant_received = []
    handoff_received = []
    bridge.assistant_text.connect(lambda h: assistant_received.append(h))
    bridge.handoff_text.connect(lambda h: handoff_received.append(h))
    callbacks = bridge.build_callbacks()
    callbacks.on_handoff()
    callbacks.on_done("**report**")
    _app.processEvents()
    assert handoff_received == ["**report**"]
    assert len(assistant_received) == 0


def test_handoff_card_is_closed_without_duplicating_content():
    """The write_handoff card must not stay "running"; its content shows once, as the answer."""
    bridge = AgentBridge()
    ended = []
    bridge.tool_ended.connect(lambda name, result: ended.append((name, result)))
    callbacks = bridge.build_callbacks()
    callbacks.on_tool_start("write_handoff", "", '{"content": "**report**"}')
    callbacks.on_handoff()
    callbacks.on_tool_end("write_handoff", "**report**")
    _app.processEvents()
    assert ended == [("write_handoff", "")]


def test_pyside_app_stays_under_file_cap():
    from pathlib import Path

    app_path = Path(__file__).parents[1] / "app.py"
    assert len(app_path.read_text(encoding="utf-8").splitlines()) <= 520
