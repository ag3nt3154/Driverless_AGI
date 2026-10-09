"""Real service bind, protected publication and capability shutdown."""
import socket
import subprocess
import sys
import time

import httpx
import pytest

from services.message_board.lifecycle import stop_local
from services.message_board.runtime_records import read_record, record_path


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(process, client, url):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("board exited before readiness")
        try:
            response = client.get(url + "/health")
            if response.status_code == 200:
                return response.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(.05)
    raise AssertionError("board did not become ready")


@pytest.mark.parametrize("host,token", [("127.0.0.1", None), ("0.0.0.0", "secret")])
def test_real_cli_stop_with_open_sse_and_wildcard(tmp_path, monkeypatch, host, token):
    port = unused_port()
    url = f"http://127.0.0.1:{port}"
    runtime = tmp_path / "run"
    args = [sys.executable, "-m", "services.message_board", "serve", "--host", host,
            "--port", str(port), "--db", str(tmp_path / "board.sqlite3"),
            "--runtime-dir", str(runtime)]
    if token:
        args.extend(["--token", token])
        monkeypatch.setenv("DAGI_BOARD_TOKEN", token)
    else:
        monkeypatch.delenv("DAGI_BOARD_TOKEN", raising=False)
    with (tmp_path / "service.log").open("wb") as log:
        process = subprocess.Popen(args, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                health = wait_ready(process, client, url)
                record = read_record(runtime, port)
                assert record["instance_id"] == health["instance_id"]
                assert record["url"] == url
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                with client.stream("GET", url + "/stream", headers=headers) as stream:
                    assert stream.status_code == 200
                    assert stop_local(url, runtime_dir=runtime) == 0
                assert process.wait(timeout=5) == 0
                assert not record_path(runtime, port).exists()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def test_bind_failure_never_publishes_record(tmp_path):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        runtime = tmp_path / "run"
        result, _ = run_cli(
            ["--port", str(port), "--db", str(tmp_path / "b.sqlite3"),
             "--runtime-dir", str(runtime)], tmp_path)
        assert result.returncode != 0
        assert not record_path(runtime, port).exists()


def test_cli_help(tmp_path):
    result, output = run_cli(["--help"], tmp_path)
    assert result.returncode == 0 and b"serve" in output and b"stop" in output


def test_secure_storage_failure_stops_startup(tmp_path):
    runtime = tmp_path / "run"
    runtime.write_text("existing file prevents secure runtime directory")
    result, output = run_cli(
        ["--port", str(unused_port()), "--db", str(tmp_path / "b.sqlite3"),
         "--runtime-dir", str(runtime)], tmp_path)
    assert result.returncode != 0
    assert b"cannot establish protected message board runtime storage" in output
    assert runtime.read_text() == "existing file prevents secure runtime directory"



def run_cli(args, tmp_path):
    path = tmp_path / "cli.log"
    with path.open("wb") as output:
        result = subprocess.run([sys.executable, "-m", "services.message_board", *args],
                                stdout=output, stderr=subprocess.STDOUT, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result, path.read_bytes()

