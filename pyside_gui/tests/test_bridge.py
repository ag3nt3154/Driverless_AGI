from __future__ import annotations

import sys
import threading
from unittest.mock import MagicMock

import pytest

import pyside_gui  # noqa: F401 — must be imported before any PySide6 import

from PySide6.QtWidgets import QApplication

from agent.affect import AffectSnapshot, AffectVector
from agent.expression_assets import TextFallback
from agent.process_state import ProcessSnapshot
from pyside_gui.bridge import AgentBridge

# PySide6 requires a QApplication to exist for QObject/Signal to work.
# Create one at module level for the test session.
_app = QApplication.instance() or QApplication(sys.argv)


def test_tool_started_signal_emits():
    bridge = AgentBridge()
    received = []
    bridge.tool_started.connect(lambda n, a: received.append((n, a)))
    callbacks = bridge.build_callbacks()
    callbacks.on_tool_start("bash", "run ls", '{"command": "ls"}')
    _app.processEvents()
    assert len(received) == 1
    assert received[0] == ("bash", '{"command": "ls"}')


def test_assistant_text_renders_markdown():
    bridge = AgentBridge()
    received = []
    bridge.assistant_text.connect(lambda h: received.append(h))
    callbacks = bridge.build_callbacks()
    callbacks.on_assistant_text("**bold**")
    _app.processEvents()
    assert len(received) == 1
    assert "<strong>bold</strong>" in received[0]


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


def test_agent_worker_reports_construction_stages(monkeypatch):
    """A pre-request stall must identify the last completed worker stage."""
    from pyside_gui.app import DagiMainWindow

    received = []
    bridge = AgentBridge()
    bridge.stage_trace.connect(received.append)
    app = DagiMainWindow.__new__(DagiMainWindow)
    app._bridge = bridge
    app._config = MagicMock()
    app._active_loop = None
    app._restore_initial_messages = None
    app._restore_initial_affect = None
    app._cmd_handler = MagicMock()
    app._invoke_on_main = MagicMock()

    class FakeLoop:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self, _task: str) -> None:
            pass

        def finish(self) -> None:
            pass

    monkeypatch.setattr("pyside_gui.app.AgentLoop", FakeLoop)

    loop_ref = []
    DagiMainWindow._agent_work(app, "merge back to main", MagicMock(), loop_ref)
    _app.processEvents()

    assert received == [
        "Stage: worker started",
        "Stage: session state captured",
        "Stage: AgentLoop construction started",
        "Stage: AgentLoop construction completed",
        "Stage: agent run started",
        "Stage: agent run completed",
    ]


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


def test_affect_and_process_snapshots_emit_as_objects(tmp_path) -> None:
    bridge = AgentBridge()
    received = []
    bridge.affect_changed.connect(lambda s: received.append(("affect", s)))
    bridge.process_state_changed.connect(
        lambda s: received.append(("process", s))
    )
    callbacks = bridge.build_callbacks()
    asset = TextFallback(tmp_path / "default.md", "test", "fallback")
    affect = AffectSnapshot(
        baseline=AffectVector(0.0, 0.0, 0.0),
        current=AffectVector(0.1, 0.2, 0.3),
        emote_id="focused",
        asset=asset,
        reason="init",
    )
    process = ProcessSnapshot("thinking", asset)

    callbacks.on_affect_changed(affect)
    callbacks.on_process_state_changed(process)
    _app.processEvents()

    assert received == [("affect", affect), ("process", process)]


def test_pyside_app_stays_under_file_cap():
    from pathlib import Path

    app_path = Path(__file__).parents[1] / "app.py"
    assert len(app_path.read_text(encoding="utf-8").splitlines()) <= 500
