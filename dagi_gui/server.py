"""NDJSON command server for the GUI sidecar.

Reads one JSON command per line from input_stream, dispatches to the
controller, and emits NDJSON events to output_stream. Exits on shutdown
command or EOF. All errors emit command_error and continue (never crash).

stdout is protocol-only; configure logs to stderr before calling serve().
"""

from __future__ import annotations

import json
import logging
import sys
from typing import TYPE_CHECKING, TextIO

from dagi_gui.protocol import EventWriter, ProtocolError, validate_command

if TYPE_CHECKING:
    from dagi_gui.session import SessionController

log = logging.getLogger(__name__)


class GuiServer:
    def __init__(self, controller: "SessionController | None" = None) -> None:
        self._controller = controller

    def serve(
        self,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        writer: "EventWriter | None" = None,
    ) -> int:
        """Run the command loop. Returns exit code (always 0)."""
        if input_stream is None:
            input_stream = sys.stdin
        if writer is None:
            writer = EventWriter(output_stream)
        writer.write("ready")

        for line in input_stream:
            line = line.strip()
            if not line:
                continue

            request_id = "?"
            try:
                raw = json.loads(line)
                # Extract request_id before validate so error includes it
                if isinstance(raw, dict):
                    request_id = str(raw.get("id", "?"))
                command = validate_command(raw)
                request_id = command["id"]

                if command["type"] == "initialize":
                    result = self._handle_initialize(command)
                elif command["type"] == "shutdown":
                    self._handle_shutdown(writer)
                    writer.write("ack", request_id=request_id, result={})
                    break
                else:
                    result = (
                        self._controller.handle(command)
                        if self._controller
                        else {}
                    )

                if command["type"] != "shutdown":
                    writer.write("ack", request_id=request_id, result=result or {})

            except (json.JSONDecodeError, ProtocolError) as exc:
                writer.write("command_error", request_id=request_id, message=str(exc))
            except Exception as exc:
                log.exception("Unhandled error in command dispatch")
                writer.write("command_error", request_id=request_id, message=str(exc))

        return 0

    def _handle_initialize(self, command: dict) -> dict:
        """Handle the initialize command; return bootstrap payload."""
        if self._controller is None:
            return {"status": "no_controller"}
        result = self._controller.handle(command)
        return result or {}

    def _handle_shutdown(self, writer: EventWriter) -> None:
        if self._controller is not None:
            self._controller.shutdown()
        writer.write("shutdown_complete")
