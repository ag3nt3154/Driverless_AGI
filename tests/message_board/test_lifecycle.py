"""Shutdown peer/auth checks and protected local lifecycle records."""
import asyncio
import errno
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from services.message_board.__main__ import parse_args
from services.message_board.app import create_app
from services.message_board.lifecycle import (
    ShutdownControl, check_bind, is_loopback_host, stop_local,
)
from services.message_board.runtime_records import (
    check_protected, read_record, record_path, remove_record, write_record,
)
from services.message_board.store import BoardStore

INSTANCE, CAPABILITY = "a" * 32, "b" * 64


@contextmanager
def stop_client(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        yield client
    finally:
        asyncio.run(client.aclose())


@pytest.fixture
def board(tmp_path):
    store = BoardStore(tmp_path / "board.sqlite3")
    yield store
    store.close()


def test_shutdown_requires_actual_peer_capability_instance_and_bearer(board):
    calls = []
    control = ShutdownControl(INSTANCE, CAPABILITY, lambda: calls.append("exit"))
    app = create_app(board, "bearer", shutdown=control)
    with TestClient(app, client=("127.0.0.1", 123)) as client:
        body = {"instance_id": INSTANCE}
        good = {"Authorization": "Bearer bearer", "X-Dagi-Stop-Token": CAPABILITY}
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            assert client.post("/shutdown", json=body, headers=headers).status_code == 401
        for capability in ("", "wrong"):
            headers = {**good, "X-Dagi-Stop-Token": capability}
            result = client.post("/shutdown", json=body, headers=headers)
            assert result.status_code == 403 and result.json()["code"] == "FORBIDDEN"
        assert client.post("/shutdown", json={"instance_id": "old"},
                           headers=good).status_code == 409
        assert calls == []
        response = client.post("/shutdown", json=body, headers=good)
        assert response.status_code == 202 and calls == ["exit"]
    with TestClient(app, client=("192.0.2.1", 123)) as client:
        result = client.post("/shutdown", json=body,
                             headers={**good, "X-Forwarded-For": "127.0.0.1"})
        assert result.status_code == 403
    with TestClient(create_app(board)) as client:
        assert client.post("/shutdown", json=body).json()["code"] == "STOP_UNAVAILABLE"


def test_exit_callback_runs_after_response_body(board):
    events = []
    control = ShutdownControl(INSTANCE, CAPABILITY, lambda: events.append("exit"))
    app = create_app(board, shutdown=control)
    import asyncio
    import json

    async def run():
        body = json.dumps({"instance_id": INSTANCE}).encode()
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/shutdown", "raw_path": b"/shutdown",
                 "query_string": b"", "server": ("127.0.0.1", 80), "client": ("127.0.0.1", 123),
                 "headers": [(b"content-type", b"application/json"),
                             (b"x-dagi-stop-token", CAPABILITY.encode())]}
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                events.append("body")
        await app(scope, receive, send)
    asyncio.run(run())
    assert events == ["body", "exit"]


def test_bind_and_argparse():
    assert parse_args([]).command == "serve"
    assert parse_args(["--port", "9001"]).port == 9001
    assert parse_args(["stop"]).command == "stop"
    for host in ("127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1"):
        assert is_loopback_host(host)
        check_bind(host, None)
    with pytest.raises(SystemExit, match="require a bearer token"):
        check_bind("0.0.0.0", None)
    check_bind("0.0.0.0", "secret")
    assert not is_loopback_host("localhost", allow_localhost=False)


def record(port=8765):
    return {"url": f"http://127.0.0.1:{port}", "port": port,
            "instance_id": INSTANCE, "capability": CAPABILITY}


def health(instance=INSTANCE, pid=123):
    return {"status": "ok", "version": 1, "pid": pid, "instance_id": instance}


def test_record_protected_atomic_and_cleanup(tmp_path):
    write_record(tmp_path / "run", record())
    path = record_path(tmp_path / "run", 8765)
    check_protected(path)
    assert read_record(tmp_path / "run", 8765) == record()
    assert list(path.parent.glob("*.json")) == [path]
    check_protected(path.parent / "board-8765.lock")
    replacement = {**record(), "instance_id": "c" * 32}
    write_record(path.parent, replacement)
    remove_record(path.parent, 8765, INSTANCE)
    assert path.exists()
    remove_record(path.parent, 8765, "c" * 32)
    assert not path.exists()


def refused():
    try:
        raise ConnectionRefusedError(errno.ECONNREFUSED, "connection refused")
    except ConnectionRefusedError as error:
        try:
            raise httpx.ConnectError("refused") from error
        except httpx.ConnectError as outer:
            return outer


@pytest.mark.parametrize("body", [health(pid=0), health(pid=-1), {"pid": 99999}, []])
def test_stop_foreign_health_never_posts(tmp_path, body):
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json=body)
    with stop_client(handler) as client:
        assert stop_local("http://localhost:8765", runtime_dir=tmp_path, client=client) == 1
    assert calls == ["GET"]


@pytest.mark.parametrize("mode", ["missing", "stale", "redirect", "timeout", "remote"])
def test_stop_rejects_without_shutdown(tmp_path, mode):
    if mode == "stale":
        write_record(tmp_path, {**record(), "instance_id": "c" * 32})
    calls = []
    def handler(request):
        calls.append(request.method)
        if mode == "timeout":
            raise httpx.ReadTimeout("health timed out")
        if mode == "redirect":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/health"})
        return httpx.Response(200, json=health())
    url = "http://example.com:8765" if mode == "remote" else "http://localhost:8765"
    with stop_client(handler) as client:
        assert stop_local(url, runtime_dir=tmp_path, client=client) == 1
    assert "POST" not in calls


@pytest.mark.parametrize("mode", ["refused", "replaced", "alive"])
def test_stop_valid_capability_and_poll(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("DAGI_BOARD_TOKEN", "bearer")
    write_record(tmp_path, record())
    calls = []
    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            assert request.headers["x-dagi-stop-token"] == CAPABILITY
            assert request.headers["authorization"] == "Bearer bearer"
            return httpx.Response(202, json={"status": "stopping"})
        if len(calls) > 1:
            if mode == "refused":
                raise refused()
            if mode == "replaced":
                return httpx.Response(200, json=health("c" * 32))
        return httpx.Response(200, json=health())
    with stop_client(handler) as client:
        result = stop_local(
            "http://localhost:8765", runtime_dir=tmp_path, client=client, wait_s=.01)
    assert result == (1 if mode == "alive" else 0)
    assert calls[:2] == ["GET", "POST"]


def test_already_down_and_unrelated_connect_error(tmp_path):
    for error, expected in ((refused(), 0), (httpx.ConnectError("DNS failure"), 1)):
        def handler(request):
            raise error
        with stop_client(handler) as client:
            result = stop_local("http://localhost:8765", runtime_dir=tmp_path, client=client)
            assert result == expected


def test_secure_record_failure_leaves_no_capability_file(tmp_path, monkeypatch):
    import services.message_board.runtime_records as records
    def reject(path):
        raise OSError("protection unavailable")
    monkeypatch.setattr(records, "check_protected", reject)
    with pytest.raises(OSError, match="protection unavailable"):
        write_record(tmp_path / "run", record())
    assert list((tmp_path / "run").glob("*.json")) == []
    assert not list((tmp_path / "run").glob("tmp*"))


def test_cleanup_and_replacement_publication_are_serialized(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import services.message_board.runtime_records as records

    write_record(tmp_path, record())
    entered, release, published = threading.Event(), threading.Event(), threading.Event()
    original = records.read_record

    def paused_read(root, port):
        value = original(root, port)
        entered.set()
        assert release.wait(5)
        return value

    monkeypatch.setattr(records, "read_record", paused_read)
    replacement = {**record(), "instance_id": "c" * 32}

    def publish():
        write_record(tmp_path, replacement)
        published.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        cleanup = pool.submit(remove_record, tmp_path, 8765, INSTANCE)
        assert entered.wait(5)
        writer = pool.submit(publish)
        try:
            assert not published.wait(.05)
        finally:
            release.set()
        cleanup.result(timeout=5)
        writer.result(timeout=5)
    assert original(tmp_path, 8765) == replacement


def test_shutdown_poll_deadline_cancels_slow_trickle_health():
    import time
    from services.message_board.lifecycle import _poll_stopped
    from services.message_board.runtime_records import RecordError

    closed = []

    class SlowHealth(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(.02)
                yield b" "
        async def aclose(self):
            closed.append(True)

    async def run():
        async def handler(request):
            return httpx.Response(200, stream=SlowHealth())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(RecordError, match="deadline"):
                await _poll_stopped(client, "http://localhost:8765", INSTANCE, .06)

    started = time.monotonic()
    asyncio.run(run())
    assert time.monotonic() - started < .3
    assert closed


def test_windows_async_connection_refusal_is_already_down(tmp_path):
    def handler(request):
        try:
            raise ConnectionRefusedError(22, "The remote computer refused the network connection",
                                         None, 1225)
        except ConnectionRefusedError as error:
            raise httpx.ConnectError("All connection attempts failed") from error
    with stop_client(handler) as client:
        assert stop_local("http://127.0.0.1:8765", runtime_dir=tmp_path, client=client) == 0
