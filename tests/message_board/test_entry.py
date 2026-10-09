"""Entry script, config-driven defaults and bearer-token resolution."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from services.message_board.__main__ import parse_args, resolve_serve_token
from services.message_board.settings import (
    BoardSettings, board_settings, ensure_token, read_token, resolve_token,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(("services", "expected"), [
    (None, BoardSettings("http://127.0.0.1:8765", "0.0.0.0")),
    ({}, BoardSettings("http://127.0.0.1:8765", "0.0.0.0")),
    ({"message_board": "http://10.0.0.5:9000"}, BoardSettings("http://10.0.0.5:9000", "0.0.0.0")),
    ({"message_board": {"url": "http://h:7000", "bind": "127.0.0.1"}},
     BoardSettings("http://h:7000", "127.0.0.1")),
    ({"message_board": {"bind": "  "}}, BoardSettings("http://127.0.0.1:8765", "0.0.0.0")),
    ({"message_board": 42}, BoardSettings("http://127.0.0.1:8765", "0.0.0.0")),
])
def test_board_settings_accepts_string_or_mapping(services, expected):
    assert board_settings(services) == expected


def test_defaults_come_from_config_and_flags_override():
    settings = BoardSettings("http://central:9100", "0.0.0.0")
    serve = parse_args([], settings)
    assert (serve.command, serve.host, serve.port) == ("serve", "0.0.0.0", 9100)
    assert parse_args(["stop"], settings).url == "http://127.0.0.1:9100"
    override = parse_args(["--host", "127.0.0.1", "--port", "9200"], settings)
    assert (override.host, override.port) == ("127.0.0.1", 9200)


def test_serve_token_precedence_for_wildcard_bind(tmp_path, monkeypatch):
    path = tmp_path / "token"
    path.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setenv("DAGI_BOARD_TOKEN", "from-env")
    assert resolve_serve_token("0.0.0.0", "explicit", path) == "explicit"
    assert resolve_serve_token("0.0.0.0", None, path) == "from-env"
    monkeypatch.delenv("DAGI_BOARD_TOKEN")
    assert resolve_serve_token("0.0.0.0", None, path) == "from-file"


def test_wildcard_bind_without_token_generates_and_stores_one(tmp_path, monkeypatch):
    monkeypatch.delenv("DAGI_BOARD_TOKEN", raising=False)
    path = tmp_path / "state" / "token"
    token = resolve_serve_token("0.0.0.0", None, path)
    assert token and len(token) >= 32
    assert read_token(path) == token
    assert resolve_serve_token("0.0.0.0", None, path) == token


def test_loopback_bind_ignores_token_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DAGI_BOARD_TOKEN", raising=False)
    path = tmp_path / "token"
    path.write_text("from-file\n", encoding="utf-8")
    assert resolve_serve_token("127.0.0.1", None, path) is None
    assert not (tmp_path / "other").exists()


def test_client_token_resolution_and_ensure(tmp_path, monkeypatch):
    monkeypatch.delenv("DAGI_BOARD_TOKEN", raising=False)
    path = tmp_path / "token"
    assert resolve_token(None, path) is None
    created = ensure_token(path)
    assert resolve_token(None, path) == created and ensure_token(path) == created
    monkeypatch.setenv("DAGI_BOARD_TOKEN", "env")
    assert resolve_token(None, path) == "env" and ensure_token(path) == "env"


def test_entry_script_runs():
    result = subprocess.run(
        [sys.executable, "message_board.py", "serve", "--help"], cwd=ROOT,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "--token" in result.stdout and "--host" in result.stdout
