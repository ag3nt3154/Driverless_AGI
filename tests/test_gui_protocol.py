"""Tests for the GUI sidecar protocol validation and event writing."""

import io
import json
import threading

import pytest

from dagi_gui.protocol import (
    COMMAND_TYPES,
    PROTOCOL_VERSION,
    EventWriter,
    ProtocolError,
    validate_command,
)


class TestValidateCommand:
    def test_requires_matching_protocol_version(self):
        with pytest.raises(ProtocolError, match="unsupported protocol version"):
            validate_command({"version": 2, "id": "1", "type": "initialize"})

    def test_accepts_valid_command(self):
        result = validate_command(
            {"version": 1, "id": "1", "type": "initialize"}
        )
        assert result["type"] == "initialize"

    def test_rejects_non_dict(self):
        with pytest.raises(ProtocolError, match="command must be an object"):
            validate_command("not a dict")

    def test_rejects_none(self):
        with pytest.raises(ProtocolError, match="command must be an object"):
            validate_command(None)

    def test_rejects_missing_id(self):
        with pytest.raises(ProtocolError, match="command id must be a non-empty"):
            validate_command({"version": 1, "type": "initialize"})

    def test_rejects_empty_id(self):
        with pytest.raises(ProtocolError, match="command id must be a non-empty"):
            validate_command({"version": 1, "id": "", "type": "initialize"})

    def test_rejects_numeric_id(self):
        with pytest.raises(ProtocolError, match="command id must be a non-empty"):
            validate_command({"version": 1, "id": 42, "type": "initialize"})

    def test_rejects_unknown_command_type(self):
        with pytest.raises(ProtocolError, match="unknown command type"):
            validate_command(
                {"version": 1, "id": "1", "type": "explode"}
            )

    def test_rejects_missing_type(self):
        with pytest.raises(ProtocolError, match="unknown command type"):
            validate_command({"version": 1, "id": "1"})

    def test_cancel_is_valid_command(self):
        result = validate_command(
            {"version": 1, "id": "c1", "type": "cancel"}
        )
        assert result["type"] == "cancel"

    @pytest.mark.parametrize("cmd_type", sorted(COMMAND_TYPES))
    def test_all_command_types_accepted(self, cmd_type):
        result = validate_command(
            {"version": 1, "id": "1", "type": cmd_type}
        )
        assert result["type"] == cmd_type

    def test_extra_fields_preserved(self):
        result = validate_command(
            {"version": 1, "id": "1", "type": "run", "task": "hello"}
        )
        assert result["task"] == "hello"

    def test_protocol_version_is_one(self):
        assert PROTOCOL_VERSION == 1


class TestEventWriter:
    def test_serializes_one_atomic_line(self):
        stream = io.StringIO()
        EventWriter(stream).write("ready", request_id="1")
        assert json.loads(stream.getvalue()) == {
            "version": 1,
            "type": "ready",
            "request_id": "1",
        }

    def test_output_ends_with_newline(self):
        stream = io.StringIO()
        EventWriter(stream).write("ready", request_id="1")
        assert stream.getvalue().endswith("\n")

    def test_exactly_one_line(self):
        stream = io.StringIO()
        EventWriter(stream).write("ready", request_id="1")
        lines = stream.getvalue().strip().split("\n")
        assert len(lines) == 1

    def test_unicode_payload(self):
        stream = io.StringIO()
        EventWriter(stream).write("assistant_message", text="Hello ☃")
        parsed = json.loads(stream.getvalue())
        assert parsed["text"] == "Hello ☃"

    def test_unicode_not_ascii_escaped(self):
        stream = io.StringIO()
        EventWriter(stream).write("assistant_message", text="☃")
        assert "\\u" not in stream.getvalue()

    def test_multiple_writes_produce_separate_lines(self):
        stream = io.StringIO()
        writer = EventWriter(stream)
        writer.write("ready", request_id="1")
        writer.write("ack", request_id="2")
        lines = stream.getvalue().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "ready"
        assert json.loads(lines[1])["type"] == "ack"

    def test_thread_safety_no_interleaving(self):
        stream = io.StringIO()
        writer = EventWriter(stream)
        errors = []

        def write_many(prefix: str, count: int):
            try:
                for i in range(count):
                    writer.write("test", source=f"{prefix}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_many, args=(f"t{t}", 50))
            for t in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        lines = stream.getvalue().strip().split("\n")
        assert len(lines) == 200
        for line in lines:
            parsed = json.loads(line)
            assert parsed["version"] == 1
            assert parsed["type"] == "test"
