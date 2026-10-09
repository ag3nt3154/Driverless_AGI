"""Qt-free GUI board lifecycle, identity and SSE behavior."""
from __future__ import annotations

import errno
import json
import socket
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
from agent.board_client import BoardClient, BoardError

def refused_error(*, windows: bool = False) -> BoardError:
    if windows:
        cause = ConnectionRefusedError(
            22, "refused", None, 1225,
        )
    else:
        cause = ConnectionRefusedError(errno.ECONNREFUSED, "refused")
    try:
        raise httpx.ConnectError("refused") from cause
    except httpx.ConnectError as error:
        board_error = BoardError("UNREACHABLE", "offline")
        board_error.__cause__ = error
        return board_error


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.timeout = 10.0
        self.registered = []
        self.closed = False

    def health(self):
        result = self.outcomes.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def register(self, handle, kind, display_name=None, host=None):
        self.registered.append((handle, kind, host))
        return {"handle": handle}

    def close(self):
        self.closed = True


class FakeSpawn:
    pid = 4321
    def __init__(self):
        self.terminated = False
        self.waited = False
        self.released = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True
        return 0

    def release(self):
        self.released = True
        return self.pid


@pytest.fixture(autouse=True)
def stub_token(monkeypatch):
    """Never write the real .dagi/board/token from a test."""
    import pyside_gui.board_runtime as runtime

    monkeypatch.setattr(runtime, "ensure_token", lambda: "generated")


def factory(client, urls=None):
    def make(url, token, **kwargs):
        if urls is not None:
            urls.append((url, token))
        return client
    return make


class Clock:
    def __init__(self):
        self.now = 0.0
    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_module_import_and_loopback_table():
    from pyside_gui.board_runtime import is_loopback_url

    accepted = [
        "http://127.0.0.1:8765", "http://localhost:1", "http://LOCALHOST.:80",
        "http://[::1]:8765", "http://127.9.8.7",
    ]
    rejected = [
        "http://example.com:8765", "https://127.0.0.1", "file://127.0.0.1/x",
        "not a url", "http://0.0.0.0:8765", "http://127.0.0.1/path",
        "http://127.0.0.1/?query=yes", "http://user@127.0.0.1/",
    ]
    assert all(is_loopback_url(value) for value in accepted)
    assert not any(is_loopback_url(value) for value in rejected)


def test_user_handle_is_created_reused_and_corrupt_value_replaced(tmp_path):
    from pyside_gui.board_runtime import load_or_create_user_handle

    path = tmp_path / "identity" / "user-handle"
    first = load_or_create_user_handle(path)
    assert first.startswith("user_") and len(first) == 13
    assert load_or_create_user_handle(path) == first
    path.write_text("BAD\n", encoding="utf-8")
    replacement = load_or_create_user_handle(path)
    assert replacement.startswith("user_") and replacement != first


def test_start_board_uses_existing_healthy_service_without_spawning(tmp_path):
    from pyside_gui.board_runtime import start_board

    client = FakeClient([{"status": "ok", "version": 1}])
    spawns = []
    runtime = start_board(
        "http://127.0.0.1:8765", None, state_dir=tmp_path,
        client_factory=lambda *args, **kwargs: client,
        spawn=lambda *args, **kwargs: spawns.append((args, kwargs)),
    )
    assert runtime.client is client and runtime.session.handle.startswith("main_")
    assert runtime.user_handle.startswith("user_") and runtime.spawned_pid is None
    assert (runtime.url, runtime.central_url) == ("http://127.0.0.1:8765", None)
    assert (tmp_path / "user_handle").read_text(encoding="utf-8").strip() == runtime.user_handle
    assert [entry[1] for entry in client.registered] == ["agent", "user"]
    assert not spawns


def test_main_handle_is_stable_across_starts(tmp_path):
    from pyside_gui.board_runtime import start_board

    handles = []
    for _ in range(2):
        client = FakeClient([{"version": 1}])
        handles.append(start_board(
            "http://127.0.0.1:8765", None, state_dir=tmp_path,
            client_factory=lambda *args, **kwargs: client,
        ).session.handle)
    assert handles[0] == handles[1]
    assert (tmp_path / "main_handle").read_text(encoding="utf-8").strip() == handles[0]


def unreachable(kind):
    if kind == "refused":
        return refused_error()
    if kind == "refused-windows":
        return refused_error(windows=True)
    if kind == "timeout":
        return BoardError("TIMEOUT", "slow")
    return BoardError("UNREACHABLE", "name resolution failed")


@pytest.mark.parametrize("kind", ["refused", "refused-windows", "timeout", "dns"])
@pytest.mark.parametrize("url", ["http://127.0.0.1:9876", "http://central.lan:9876"])
def test_unreachable_twice_launches_local_board(tmp_path, url, kind):
    from pyside_gui.board_runtime import start_board

    client = FakeClient([unreachable(kind), unreachable(kind), {"status": "ok", "version": 1}])
    child, calls, urls, clock = FakeSpawn(), [], [], Clock()

    def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return child

    runtime = start_board(
        url, None, state_dir=tmp_path, client_factory=factory(client, urls), spawn=spawn,
        sleep=clock.sleep, clock=clock,
    )
    assert runtime.spawned_pid == child.pid and child.released
    assert not child.terminated and not child.waited
    args, kwargs = calls[0]
    assert args[:2] == ("0.0.0.0", 9876)
    assert kwargs["db_path"] == tmp_path / "board.sqlite3"
    assert kwargs["runtime_dir"] == tmp_path / "run"
    assert urls == [(url, None), ("http://127.0.0.1:9876", "generated")]
    assert runtime.url == "http://127.0.0.1:9876"
    assert runtime.central_url == (None if "127.0.0.1" in url else url)
    assert clock.now >= 2.0


def test_retry_success_does_not_spawn(tmp_path):
    from pyside_gui.board_runtime import start_board

    client, spawns, clock = FakeClient([refused_error(), {"version": 1}]), [], Clock()
    runtime = start_board(
        "http://central.lan:8765", "secret", state_dir=tmp_path,
        client_factory=factory(client), spawn=lambda *a, **k: spawns.append(1),
        sleep=clock.sleep, clock=clock,
    )
    assert not spawns and runtime.central_url is None and clock.now == 2.0


def test_configured_token_is_used_for_the_local_board(tmp_path):
    from pyside_gui.board_runtime import start_board

    client, urls, clock = FakeClient([refused_error(), refused_error(), {"version": 1}]), [], Clock()
    start_board(
        "http://127.0.0.1:8765", "secret", state_dir=tmp_path, bind="127.0.0.1",
        client_factory=factory(client, urls), spawn=lambda *a, **k: FakeSpawn(),
        sleep=clock.sleep, clock=clock,
    )
    assert urls[-1] == ("http://127.0.0.1:8765", "secret")


@pytest.mark.parametrize("code", ["UNAUTHORIZED", "FORBIDDEN"])
def test_auth_failure_never_spawns(tmp_path, code):
    from pyside_gui.board_runtime import start_board

    client, spawns = FakeClient([BoardError(code, "bad token")]), []
    with pytest.raises(BoardError) as caught:
        start_board("http://central.lan:8765", None, state_dir=tmp_path,
                    client_factory=factory(client),
                    spawn=lambda *args, **kwargs: spawns.append(1))
    assert caught.value.code == code and not spawns


def test_foreign_health_never_spawns(tmp_path):
    from pyside_gui.board_runtime import start_board

    client, spawns = FakeClient([{"status": "ok"}]), []
    with pytest.raises(BoardError) as caught:
        start_board("http://127.0.0.1:8765", None, state_dir=tmp_path,
                    client_factory=lambda *args, **kwargs: client,
                    spawn=lambda *args, **kwargs: spawns.append(1))
    assert caught.value.code == "NOT_A_BOARD" and not spawns


@pytest.mark.parametrize("outcome", [
    BoardError("INVALID_RESPONSE", "bad JSON"), BoardError("HTTP_404", "missing"),
    ValueError("wrong shape"),
])
def test_malformed_or_foreign_health_maps_to_not_a_board(tmp_path, outcome):
    from pyside_gui.board_runtime import start_board

    client, spawns = FakeClient([outcome]), []
    with pytest.raises(BoardError) as caught:
        start_board(
            "http://127.0.0.1:8765", None, state_dir=tmp_path,
            client_factory=lambda *args, **kwargs: client,
            spawn=lambda *args, **kwargs: spawns.append(1),
        )
    assert caught.value.code == "NOT_A_BOARD" and not spawns and client.closed


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_or_cancelled_spawn_cleans_up_only_owned_child(tmp_path, cancelled):
    from pyside_gui.board_runtime import start_board

    clock, child = Clock(), FakeSpawn()
    cancel = threading.Event()

    def spawn(*args, **kwargs):
        if cancelled:
            cancel.set()
        return child

    client = FakeClient([refused_error() for _ in range(8)])
    with pytest.raises(BoardError) as caught:
        start_board(
            "http://127.0.0.1:8765", None, state_dir=tmp_path,
            client_factory=factory(client), spawn=spawn, wait_s=.3,
            sleep=clock.sleep, clock=clock, cancel=cancel,
        )
    assert caught.value.code == ("CANCELLED" if cancelled else "SPAWN_FAILED")
    assert child.terminated and child.waited and not child.released
    assert client.closed


def test_cancel_during_retry_does_not_spawn(tmp_path):
    from pyside_gui.board_runtime import start_board

    cancel, spawns = threading.Event(), []
    client = FakeClient([refused_error(), refused_error()])
    with pytest.raises(BoardError) as caught:
        start_board(
            "http://127.0.0.1:8765", None, state_dir=tmp_path,
            client_factory=factory(client), spawn=lambda *a, **k: spawns.append(1),
            sleep=lambda _seconds: cancel.set(), cancel=cancel,
        )
    assert caught.value.code == "CANCELLED" and not spawns and client.closed


def test_cancel_existing_service_does_not_spawn_or_terminate(tmp_path):
    from pyside_gui.board_runtime import start_board

    cancel, spawns = threading.Event(), []
    cancel.set()
    client = FakeClient([{"status": "ok", "version": 1}])
    with pytest.raises(BoardError) as caught:
        start_board(
            "http://127.0.0.1:8765", None, state_dir=tmp_path,
            client_factory=lambda *args, **kwargs: client,
            spawn=lambda *args, **kwargs: spawns.append(1), cancel=cancel,
        )
    assert caught.value.code == "CANCELLED" and not spawns
    assert client.closed


@pytest.mark.parametrize("spawned", [False, True])
def test_registration_failure_closes_client_and_retains_child_ownership(tmp_path, spawned):
    from pyside_gui.board_runtime import start_board

    outcomes = [refused_error()] * 2 + [{"version": 1}] if spawned else [{"version": 1}]
    client, child = FakeClient(outcomes), FakeSpawn()

    def fail_register(*args, **kwargs):
        raise BoardError("HANDLE_TAKEN", "conflict")

    client.register = fail_register
    with pytest.raises(BoardError, match="conflict"):
        start_board(
            "http://127.0.0.1:8765", None, state_dir=tmp_path,
            client_factory=lambda *args, **kwargs: client,
            spawn=lambda *args, **kwargs: child, sleep=lambda _seconds: None,
        )
    assert client.closed
    assert (child.terminated, child.waited, child.released) == (
        spawned, spawned, False,
    )


def test_invalid_service_root_fails_before_client_or_spawn(tmp_path):
    from pyside_gui.board_runtime import start_board

    calls = []
    with pytest.raises(BoardError) as caught:
        start_board(
            "http://127.0.0.1:8765/path?x=1", None, state_dir=tmp_path,
            client_factory=lambda *args, **kwargs: calls.append("client"),
            spawn=lambda *args, **kwargs: calls.append("spawn"),
        )
    assert caught.value.code == "NOT_A_BOARD" and calls == []


def test_parse_sse_ignores_ping_and_combines_split_data():
    from pyside_gui.board_runtime import parse_sse

    lines = [
        ": ping", "", "event: post", 'data: {"id": 1,',
        'data: "text": "one"}', "", "event: other", 'data: {"id": 9}', "",
        "event: post", 'data: {"id": 2, "text": "two"}', "",
    ]
    assert list(parse_sse(lines)) == [
        {"id": 1, "text": "one"}, {"id": 2, "text": "two"},
    ]


class ClosableLines:
    def __init__(self, lines, block=None):
        self.lines = iter(lines)
        self.block = block
        self.closed = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self.lines)
        except StopIteration:
            if self.block is None:
                raise
            self.block.set()
            self.closed.wait(5)
            raise StopIteration

    def close(self):
        self.closed.set()


class StreamClient:
    def __init__(self, streams):
        self.streams = iter(streams)
        self.after = []
        self.active = None

    @contextmanager
    def stream(self, after=None):
        self.after.append(after)
        item = next(self.streams)
        if isinstance(item, BaseException):
            raise item
        self.active = item
        try:
            yield item
        finally:
            item.close()


def test_listener_reconnects_and_dedupes_overlapping_posts():
    from pyside_gui.board_runtime import StreamListener

    first = BoardError("UNREACHABLE", "reset")
    replay = ClosableLines([
        "event: post", 'data: {"id": 2}', "",
        "event: post", 'data: {"id": 3}', "",
    ])
    client = StreamClient([first, replay])
    posts, statuses = [], []
    listener = None

    def receive(post):
        posts.append(post)
        listener.stop()

    listener = StreamListener(client, 2, receive, statuses.append, backoff=(0.0,))
    listener.start()
    listener.join(timeout=1)
    assert posts == [{"id": 3}] and client.after == [2, 2]
    assert statuses[0].startswith("reconnecting: ") and "connected" in statuses


def test_listener_stop_closes_active_iterator_promptly():
    from pyside_gui.board_runtime import StreamListener

    blocking = threading.Event()
    lines = ClosableLines([], block=blocking)
    listener = StreamListener(StreamClient([lines]), 0, lambda post: None, lambda status: None)
    listener.start()
    assert blocking.wait(1)
    listener.stop()
    listener.join(timeout=1)
    assert not listener.is_alive() and lines.closed.is_set()


def test_listener_stop_during_stream_entry_closes_before_callback():
    from pyside_gui.board_runtime import StreamListener

    entered, release = threading.Event(), threading.Event()
    lines, statuses = ClosableLines([]), []

    class GatedClient:
        @contextmanager
        def stream(self, after=None):
            entered.set()
            assert release.wait(1)
            try:
                yield lines
            finally:
                lines.close()

    listener = StreamListener(GatedClient(), 0, lambda post: None, statuses.append)
    listener.start()
    assert entered.wait(1)
    listener.stop()
    release.set()
    listener.join(timeout=1)
    assert not listener.is_alive() and lines.closed.is_set() and statuses == []


def test_listener_increases_backoff_for_repeated_empty_disconnects():
    from pyside_gui.board_runtime import StreamListener

    client = StreamClient([ClosableLines([]) for _ in range(3)])
    listener = StreamListener(client, 0, lambda post: None, lambda status: None)

    class StopAfterThreeWaits:
        def __init__(self):
            self.delays = []
            self.stopped = False

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def wait(self, delay):
            self.delays.append(delay)
            self.stopped = len(self.delays) == 3
            return self.stopped

    event = StopAfterThreeWaits()
    listener._stop_event = event
    listener.run()
    assert event.delays == [1.0, 2.0, 4.0]


def test_spawn_service_command_and_detachment(monkeypatch, tmp_path):
    import pyside_gui.board_runtime as runtime

    captured = {}

    class Process:
        pid = 99

        def __init__(self, command, **kwargs):
            captured.update(command=command, **kwargs)

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(runtime.subprocess, "Popen", Process)
    child = runtime.spawn_service(
        "127.0.0.1", 8765, tmp_path / "board.log",
        db_path=tmp_path / "b.sqlite3", runtime_dir=tmp_path / "run",
    )
    assert child.pid == 99
    assert captured["command"][1:5] == ["-m", "services.message_board", "serve", "--host"]
    assert "--db" in captured["command"] and "--runtime-dir" in captured["command"]
    assert captured["cwd"] == runtime.DAGI_ROOT and captured["stdin"] is runtime.subprocess.DEVNULL
    assert captured["close_fds"] is True
    if runtime.os.name == "nt":
        expected = sum(getattr(runtime.subprocess, name) for name in (
            "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW",
        ))
        assert captured["creationflags"] == expected
    else:
        assert captured["start_new_session"] is True


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_live_detached_service_stream_and_stop(tmp_path):
    from pyside_gui.board_runtime import StreamListener, spawn_service
    from services.message_board.lifecycle import stop_local

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    runtime_dir = tmp_path / "run"
    child = spawn_service(
        "127.0.0.1", port, tmp_path / "board.log",
        db_path=tmp_path / "board.sqlite3", runtime_dir=runtime_dir,
    )
    client = BoardClient(url, timeout=.5)
    stopped = False
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                if client.health().get("version") == 1:
                    break
            except BoardError:
                if time.monotonic() >= deadline:
                    pytest.fail((tmp_path / "board.log").read_text(errors="replace"))
                time.sleep(.1)
        handle = "live_1234abcd"
        client.register(handle, "agent", host="test")
        posts, received = [], threading.Event()
        listener = StreamListener(
            client, 0, lambda post: (posts.append(post), received.set()), lambda status: None,
        )
        listener.start()
        client.post(handle, "live event")
        assert received.wait(10)
        listener.stop()
        listener.join(timeout=2)
        assert posts[-1]["text"] == "live event"
        assert stop_local(url, runtime_dir=runtime_dir, wait_s=5) == 0
        stopped = True
        with pytest.raises(BoardError):
            client.health()
    finally:
        client.close()
        if not stopped:
            child.terminate()
            child.wait(timeout=5)
