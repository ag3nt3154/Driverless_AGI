"""Entry script, config-driven defaults and bearer-token resolution."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from services.message_board import __main__ as board_main
from services.message_board.__main__ import main, parse_args, resolve_serve_token
from services.message_board.settings import (
    DEFAULT_TOKEN, BoardSettings, board_settings, resolve_token,
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


def _env_file(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_token_precedence_explicit_then_env_then_dotenv_then_default(tmp_path, monkeypatch):
    env_file = _env_file(tmp_path, "OTHER=1\nDAGI_BOARD_TOKEN=from-dotenv\n")
    monkeypatch.setenv("DAGI_BOARD_TOKEN", "from-env")
    assert resolve_token("explicit", env_file) == "explicit"
    assert resolve_token(None, env_file) == "from-env"
    monkeypatch.delenv("DAGI_BOARD_TOKEN")
    assert resolve_token(None, env_file) == "from-dotenv"
    assert resolve_token(None, tmp_path / "missing.env") == DEFAULT_TOKEN == "dagi"


def test_blank_values_fall_through_to_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_BOARD_TOKEN", "  ")
    env_file = _env_file(tmp_path, "DAGI_BOARD_TOKEN=\n")
    assert resolve_token("", env_file) == "dagi"


def test_reading_dotenv_does_not_change_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("DAGI_BOARD_TOKEN", raising=False)
    env_file = _env_file(tmp_path, "DAGI_BOARD_TOKEN=from-dotenv\n")
    assert resolve_token(None, env_file) == "from-dotenv"
    assert "DAGI_BOARD_TOKEN" not in __import__("os").environ


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_every_serve_bind_gets_a_token(tmp_path, monkeypatch, host):
    monkeypatch.delenv("DAGI_BOARD_TOKEN", raising=False)
    missing = tmp_path / "missing.env"
    assert resolve_serve_token(host, None, env_path=missing) == "dagi"
    assert resolve_serve_token(host, "secret", env_path=missing) == "secret"


def test_default_token_warns_only_on_a_network_bind(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DAGI_BOARD_TOKEN", raising=False)
    missing = tmp_path / "missing.env"
    resolve_serve_token("127.0.0.1", None, env_path=missing)
    resolve_serve_token("0.0.0.0", "custom-secret", env_path=missing)
    assert capsys.readouterr().err == ""
    resolve_serve_token("0.0.0.0", None, env_path=missing)
    err = capsys.readouterr().err
    assert 'default token "dagi"' in err and "DAGI_BOARD_TOKEN" in err and ".env" in err


def test_no_token_is_loopback_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_BOARD_TOKEN", "from-env")
    assert resolve_serve_token("127.0.0.1", None, no_token=True) is None
    with pytest.raises(SystemExit, match="loopback"):
        resolve_serve_token("0.0.0.0", None, no_token=True)


def test_no_token_and_token_flags_are_exclusive(capsys):
    assert parse_args(["serve", "--no-token"]).no_token is True
    with pytest.raises(SystemExit):
        parse_args(["serve", "--no-token", "--token", "x"])


def test_entry_script_runs():
    result = subprocess.run(
        [sys.executable, "message_board.py", "serve", "--help"], cwd=ROOT,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "--token" in result.stdout and "--host" in result.stdout
    assert "--no-browser" in result.stdout


def test_running_board_only_opens_browser(tmp_path, capsys):
    served = []
    opened = []

    result = main(["--port", "9", "--runtime-dir", str(tmp_path / "run")], open_browser=True,
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
        on_start(instance_id, "k" * 43)
        assert ready.wait(2)

    def opener(url):
        opened.append(url)
        ready.set()

    assert main(["--port", "9"], open_browser=True, opener=opener,
                probe=probe, serve=serve) == 0
    assert calls[0] == "http://127.0.0.1:9"
    assert len(calls) == 2
    assert opened == ["http://127.0.0.1:9/#admin=" + "k" * 43]


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
        on_start("a" * 32, "k" * 43)
        assert probed.wait(2)

    assert main(["--port", "9"], open_browser=True, opener=opened.append,
                probe=probe, serve=serve) == 0
    assert opened == []


def test_fresh_start_opens_admin_fragment(monkeypatch):
    import threading

    class Store:
        def __init__(self, path):
            pass

        def close(self):
            pass

    controls = []
    opened = []
    ready = threading.Event()

    class Server:
        def __init__(self, config, *, runtime_dir, control):
            self.should_exit = False
            controls.append(control)

        def run(self):
            assert ready.wait(2)

    def opener(url):
        opened.append(url)
        ready.set()

    monkeypatch.setattr(board_main, "BoardStore", Store)
    monkeypatch.setattr(board_main, "RecordServer", Server)
    monkeypatch.setattr(board_main, "resolve_serve_token", lambda *a, **k: "t")

    assert main(["--host", "127.0.0.1", "--port", "9"], open_browser=True, opener=opener,
                probe=lambda url: controls[0].instance_id if controls else None) == 0
    key = controls[0].admin_key
    assert len(key) >= 32
    assert opened == ["http://127.0.0.1:9/#admin=" + key]


def _write_running_record(runtime, port, instance_id, **extra):
    from services.message_board.runtime_records import write_record

    write_record(runtime, {"url": f"http://127.0.0.1:{port}", "port": port,
                           "instance_id": instance_id, "capability": "c" * 64, **extra})


def test_already_running_opens_admin_fragment_from_record(tmp_path, capsys):
    runtime = tmp_path / "run"
    key = "K" * 43
    _write_running_record(runtime, 9, "a" * 32, admin_key=key)
    opened = []

    assert main(["--port", "9", "--runtime-dir", str(runtime)], open_browser=True,
                opener=opened.append, probe=lambda url: "a" * 32,
                serve=lambda *a, **k: pytest.fail("must not serve")) == 0

    assert opened == ["http://127.0.0.1:9/#admin=" + key]
    captured = capsys.readouterr()
    assert captured.out == "message board already running at http://127.0.0.1:9/\n"
    assert key not in captured.out + captured.err


@pytest.mark.parametrize(("record", "reason"), [
    ({"instance_id": "b" * 32, "admin_key": "K" * 43}, "belongs to another instance"),
    ({"instance_id": "a" * 32}, "no admin key"),
    ({"instance_id": "a" * 32, "admin_key": ""}, "no admin key"),
    (None, ""),
])
def test_already_running_with_stale_record_opens_plain_url(tmp_path, capsys, record, reason):
    runtime = tmp_path / "run"
    if record is not None:
        _write_running_record(runtime, 9, **record)
    opened = []

    assert main(["--port", "9", "--runtime-dir", str(runtime)], open_browser=True,
                opener=opened.append, probe=lambda url: "a" * 32,
                serve=lambda *a, **k: pytest.fail("must not serve")) == 0

    assert opened == ["http://127.0.0.1:9/"]
    captured = capsys.readouterr()
    assert captured.out == "message board already running at http://127.0.0.1:9/\n"
    assert captured.err.startswith("admin controls unavailable: ")
    assert reason in captured.err
    assert "K" * 43 not in captured.err


def test_runtime_record_contains_admin_key(tmp_path):
    import asyncio

    import uvicorn

    from services.message_board.lifecycle import ShutdownControl
    from services.message_board.runtime_records import read_record

    async def app(scope, receive, send):
        pass

    control = ShutdownControl("a" * 32, "c" * 64, lambda: None, admin_key="K" * 43)
    runtime = tmp_path / "run"

    async def run():
        config = uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off",
                                log_level="warning")
        server = board_main.RecordServer(config, runtime_dir=runtime, control=control)
        config.load()
        server.lifespan = config.lifespan_class(config)
        await server.startup()
        try:
            return read_record(runtime, server.record_port)
        finally:
            await server.shutdown()

    record = asyncio.run(run())
    assert record["admin_key"] == "K" * 43
    assert record["instance_id"] == "a" * 32


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


def test_lan_hint_points_at_dotenv_without_printing_the_token(tmp_path, monkeypatch, capsys):
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

    env_path = tmp_path / ".env"
    monkeypatch.setattr(board_main, "ENV_PATH", env_path)
    monkeypatch.setattr(board_main.socket, "gethostname", lambda: "ship-host")
    monkeypatch.setattr(board_main, "BoardStore", Store)
    monkeypatch.setattr(board_main, "RecordServer", Server)
    monkeypatch.setattr(board_main, "resolve_serve_token", lambda *a, **k: "do-not-print-this")

    board_main.serve_board(board_main.parse_args(["--host", "192.168.1.20", "--port", "9123"]))

    output = capsys.readouterr().out
    assert output == f"LAN: http://ship-host:9123/ (token: DAGI_BOARD_TOKEN in {env_path})\n"
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
