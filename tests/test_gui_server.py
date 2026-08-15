"""Tests for the GUI NDJSON server entrypoint."""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from dagi_gui.protocol import PROTOCOL_VERSION
from dagi_gui.server import GuiServer


# ── Test helpers ──────────────────────────────────────────────────────────────

def cmd(id: str, type: str, **kwargs) -> str:
    return json.dumps({"version": PROTOCOL_VERSION, "id": id, "type": type, **kwargs}) + "\n"


def read_events(output: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]


class FakeController:
    def __init__(self, responses: dict[str, Any] | None = None, raise_on: str | None = None):
        self._responses = responses or {}
        self._raise_on = raise_on
        self.handled: list[dict] = []
        self._shutdown_called = False

    def handle(self, command: dict) -> object:
        self.handled.append(command)
        if self._raise_on and command.get("type") == self._raise_on:
            raise RuntimeError(f"error in {self._raise_on}")
        return self._responses.get(command["type"], {})

    def shutdown(self) -> None:
        self._shutdown_called = True

    @property
    def _writer(self):
        return MagicMock()


# ── Server tests ──────────────────────────────────────────────────────────────

class TestGuiServer:
    def _run(self, commands: list[str], controller=None) -> list[dict]:
        inp = io.StringIO("".join(commands))
        out = io.StringIO()
        ctrl = controller or FakeController()
        server = GuiServer(controller=ctrl)
        server.serve(inp, out)
        return read_events(out)

    def test_initialize_emits_ready(self):
        events = self._run([
            cmd("1", "initialize"),
            cmd("2", "shutdown"),
        ])
        types = [e["type"] for e in events]
        assert "ready" in types

    def test_ready_before_ack(self):
        events = self._run([
            cmd("1", "initialize"),
            cmd("2", "shutdown"),
        ])
        types = [e["type"] for e in events]
        ready_idx = types.index("ready")
        ack_idx = types.index("ack")
        assert ready_idx < ack_idx

    def test_ack_has_matching_request_id(self):
        events = self._run([
            cmd("req-42", "initialize"),
            cmd("shutdown-1", "shutdown"),
        ])
        acks = [e for e in events if e["type"] == "ack"]
        assert any(a["request_id"] == "req-42" for a in acks)

    def test_shutdown_emits_shutdown_complete(self):
        events = self._run([cmd("s1", "shutdown")])
        types = [e["type"] for e in events]
        assert "shutdown_complete" in types

    def test_invalid_json_emits_command_error_and_continues(self):
        events = self._run([
            "not valid json\n",
            cmd("1", "shutdown"),
        ])
        types = [e["type"] for e in events]
        assert "command_error" in types
        assert "shutdown_complete" in types

    def test_invalid_version_emits_command_error_and_continues(self):
        bad = json.dumps({"version": 99, "id": "1", "type": "run"}) + "\n"
        events = self._run([
            bad,
            cmd("1", "shutdown"),
        ])
        types = [e["type"] for e in events]
        assert "command_error" in types
        assert "shutdown_complete" in types

    def test_handler_error_emits_command_error_and_continues(self):
        ctrl = FakeController(raise_on="run")
        events = self._run([
            cmd("r1", "run", task="hello"),
            cmd("s1", "shutdown"),
        ], controller=ctrl)
        types = [e["type"] for e in events]
        assert "command_error" in types
        assert "shutdown_complete" in types

    def test_eof_exits_cleanly(self):
        # No shutdown command — EOF should exit cleanly
        events = self._run([
            cmd("1", "initialize"),
        ])
        # Should have emitted ready + ack without crashing
        types = [e["type"] for e in events]
        assert "ready" in types

    def test_multiple_commands_all_acknowledged(self):
        events = self._run([
            cmd("1", "initialize"),
            cmd("2", "run", task="hello"),
            cmd("3", "shutdown"),
        ])
        ack_ids = {e["request_id"] for e in events if e["type"] == "ack"}
        assert "1" in ack_ids
        assert "2" in ack_ids

    def test_command_error_includes_request_id(self):
        bad = json.dumps({"version": 99, "id": "bad-1", "type": "run"}) + "\n"
        events = self._run([bad, cmd("s1", "shutdown")])
        errors = [e for e in events if e["type"] == "command_error"]
        assert errors[0]["request_id"] == "bad-1"
