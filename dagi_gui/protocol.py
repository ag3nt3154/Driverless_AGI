"""Versioned NDJSON protocol for the GUI sidecar.

stdout is protocol-only; diagnostics go to stderr.
EventWriter forces line-buffered output to prevent Windows block-buffering
deadlocks when stdout is piped to the Electron supervisor.
"""

import json
import sys
import threading
from typing import TextIO

PROTOCOL_VERSION = 1

COMMAND_TYPES = {
    "initialize",
    "run",
    "cancel",
    "pause",
    "resume",
    "answer_question",
    "compact",
    "clear",
    "set_model",
    "set_project",
    "list_tools",
    "list_skills",
    "list_workflows",
    "invoke_skill",
    "invoke_workflow",
    "list_history",
    "restore_history",
    "initialize_project",
    "shutdown",
}


class ProtocolError(ValueError):
    pass


def validate_command(value: object) -> dict[str, object]:
    """Validate an inbound command dict; raise ProtocolError on any violation."""
    if not isinstance(value, dict):
        raise ProtocolError("command must be an object")
    if value.get("version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    if not isinstance(value.get("id"), str) or not value["id"]:
        raise ProtocolError("command id must be a non-empty string")
    if value.get("type") not in COMMAND_TYPES:
        raise ProtocolError("unknown command type")
    return value


class EventWriter:
    """Thread-safe NDJSON event writer.

    Forces line buffering on the underlying stream so every write flushes
    immediately — essential on Windows where piped stdout defaults to block
    buffering, which would deadlock the Electron supervisor waiting for ready.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        if stream is None:
            stream = open(  # noqa: WPS515
                sys.stdout.fileno(),
                "w",
                buffering=1,
                encoding="utf-8",
                closefd=False,
            )
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, event_type: str, **payload: object) -> None:
        """Serialize and emit one event as a single NDJSON line."""
        line = json.dumps(
            {"version": PROTOCOL_VERSION, "type": event_type, **payload},
            ensure_ascii=False,
        )
        with self._lock:
            self._stream.write(line + "\n")
            if hasattr(self._stream, "flush"):
                self._stream.flush()
