"""Entry script, config-driven defaults and bearer-token resolution."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from services.message_board import __main__ as board_main
from services.message_board.__main__ import main, parse_args, resolve_serve_token
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
    assert "--no-browser" in result.stdout


def test_running_board_only_opens_browser(capsys):
    served = []
    opened = []

    result = main(["--port", "9"], open_browser=True,
                  opener=opened.append, probe=lambda url: True,
                  serve=served.append)

    assert result == 0
    assert opened == ["http://127.0.0.1:9/"]
    assert served == []
    assert capsys.readouterr().out == "message board already running at http://127.0.0.1:9/\n"


def test_no_browser_flag_skips_opener(monkeypatch):
    opened = []
    monkeypatch.setattr("services.message_board.__main__.serve_board", lambda args: None)

    assert main(["--port", "9", "--no-browser"], open_browser=True,
                opener=opened.append, probe=lambda url: False) == 0
    assert opened == []


def test_module_entry_never_opens_browser(monkeypatch):
    opened = []
    monkeypatch.setattr("services.message_board.__main__.serve_board", lambda args: None)

    assert main(["--port", "9"], opener=opened.append, probe=lambda url: True) == 0
    assert opened == []


def test_browser_opens_after_health_answers():
    import threading

    opened = []
    calls = []
    ready = threading.Event()
    instance_id = "a" * 32

    def probe(url):
        calls.append(url)
        return instance_id if len(calls) >= 2 else None

    def serve(args, *, on_start):
        on_start(instance_id)
        assert ready.wait(2)

    def opener(url):
        opened.append(url)
        ready.set()

    assert main(["--port", "9"], open_browser=True, opener=opener,
                probe=probe, serve=serve) == 0
    assert calls[0] == "http://127.0.0.1:9"
    assert len(calls) == 2
    assert opened == ["http://127.0.0.1:9/"]


def test_foreign_instance_never_opens_during_readiness():
    import threading

    probed = threading.Event()
    opened = []
    calls = []

    def probe(url):
        calls.append(url)
        if len(calls) == 1:
            return None
        probed.set()
        return "b" * 32

    def serve(args, *, on_start):
        on_start("a" * 32)
        assert probed.wait(2)

    assert main(["--port", "9"], open_browser=True, opener=opened.append,
                probe=probe, serve=serve) == 0
    assert opened == []


@pytest.mark.parametrize("body", [
    {"status": "ok", "version": 1, "pid": 123},
    {"status": "ok", "version": 1, "pid": 0, "instance_id": "a" * 32},
    {"status": "ok", "version": 1, "pid": 123, "instance_id": "A" * 32},
    {"status": "ok", "version": True, "pid": 123, "instance_id": "a" * 32},
    {"status": "foreign", "version": 1, "pid": 123, "instance_id": "a" * 32},
])
def test_health_probe_rejects_invalid_or_missing_identity(body, monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return body

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            return Response()

    monkeypatch.setattr(board_main.httpx, "Client", Client)
    assert board_main._probe_v1("http://127.0.0.1:9") is None


def test_health_probe_disables_environment_proxies(monkeypatch):
    seen = {}
    instance_id = "a" * 32

    class Response:
        status_code = 200

        def json(self):
            return {"status": "ok", "version": 1, "pid": 123,
                    "instance_id": instance_id}

    class Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            return Response()

    monkeypatch.setattr(board_main.httpx, "Client", Client)
    assert board_main._probe_v1("http://127.0.0.1:9") == instance_id
    assert seen["trust_env"] is False


def test_lan_hint_uses_hostname_port_and_token_path_without_token(tmp_path, monkeypatch, capsys):
    class Store:
        def __init__(self, path):
            pass

        def close(self):
            pass

    class Server:
        def __init__(self, config, *, runtime_dir, control):
            self.should_exit = False

        def run(self):
            pass

    token_path = tmp_path / "private-token"
    monkeypatch.setattr(board_main, "TOKEN_PATH", token_path)
    monkeypatch.setattr(board_main.socket, "gethostname", lambda: "ship-host")
    monkeypatch.setattr(board_main, "BoardStore", Store)
    monkeypatch.setattr(board_main, "RecordServer", Server)
    monkeypatch.setattr(board_main, "resolve_serve_token", lambda *args: "do-not-print-this")

    board_main.serve_board(board_main.parse_args(["--host", "192.168.1.20", "--port", "9123"]))

    output = capsys.readouterr().out
    assert output == f"LAN: http://ship-host:9123/ (token in {token_path})\n"
    assert "do-not-print-this" not in output


def test_load_settings_reads_yaml_without_the_agent_stack(tmp_path):
    from services.message_board.settings import load_settings

    config = tmp_path / "config.yaml"
    config.write_text("services:\n  message_board:\n    url: http://h:9100\n    bind: 127.0.0.1\n",
                      encoding="utf-8")
    assert load_settings(config) == BoardSettings("http://h:9100", "127.0.0.1")
    assert load_settings(tmp_path / "missing.yaml") == BoardSettings()
    probe = ("import sys; from services.message_board.__main__ import parse_args; parse_args([]); "
             "print('agent.loop' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True,
                            text=True, timeout=60)
    assert result.stdout.strip() == "False", result.stderr
