"""Qt-free GUI board lifecycle, temporary ownership and SSE behavior."""
from __future__ import annotations

import errno
import json
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
from agent.board_client import BoardClient, BoardError


def refused_error():
    try:
        raise httpx.ConnectError("refused") from ConnectionRefusedError(errno.ECONNREFUSED, "refused")
    except httpx.ConnectError as error:
        result = BoardError("UNREACHABLE", "offline")
        result.__cause__ = error
        return result


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


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_loopback_url_classification():
    from pyside_gui.board_runtime import is_loopback_url

    accepted = ["http://127.0.0.1:8765", "http://localhost:1", "http://[::1]:8765"]
    rejected = ["http://central.lan:8765", "https://127.0.0.1", "http://0.0.0.0:8765"]
    assert all(is_loopback_url(value) for value in accepted)
    assert not any(is_loopback_url(value) for value in rejected)


def test_temp_board_api_is_available():
    from pyside_gui.board_runtime import DAGI_ROOT, TempBoard, sweep_stale

    assert callable(TempBoard.start) and callable(sweep_stale)
    assert TempBoard.start.__func__.__defaults__[0] == DAGI_ROOT / ".dagi" / "board" / "temp"


def test_temp_board_setup_failure_removes_partial_run_and_releases_lifecycle_lock(
    monkeypatch, tmp_path,
):
    import pyside_gui.board_runtime as runtime
    from services.message_board.runtime_records import lock_file, open_lock

    root = tmp_path / "temp"
    original_protect = runtime.protect

    def fail_run_protect(path):
        path = runtime.Path(path)
        if path.parent == root and len(path.name) == 8:
            raise OSError("simulated owner directory protection failure")
        return original_protect(path)

    monkeypatch.setattr(runtime, "protect", fail_run_protect)
    with pytest.raises(OSError, match="simulated owner directory protection failure"):
        runtime.TempBoard.start(root=root, spawn=lambda *a, **k: pytest.fail("spawned"))

    assert list(root.iterdir()) == [root / ".lifecycle.lock"]
    lifecycle = open_lock(root / ".lifecycle.lock")
    try:
        assert lock_file(lifecycle, blocking=False)
    finally:
        lock_file(lifecycle, unlock=True)
        lifecycle.close()


def test_temp_board_uuid_collision_preserves_existing_run_and_releases_lifecycle_lock(
    monkeypatch, tmp_path,
):
    import pyside_gui.board_runtime as runtime
    from services.message_board.runtime_records import lock_file, open_lock

    root = tmp_path / "temp"
    existing = root / "deadbeef"
    existing.mkdir(parents=True)
    marker = existing / "marker.txt"
    marker.write_text("keep me", encoding="utf-8")
    owner = open_lock(existing / "owner.lock")
    assert lock_file(owner, blocking=False)
    monkeypatch.setattr(runtime.uuid, "uuid4", lambda: type("Id", (), {"hex": "deadbeef"})())
    spawn_calls = []

    try:
        with pytest.raises(FileExistsError):
            runtime.TempBoard.start(
                root=root, spawn=lambda *a, **k: spawn_calls.append((a, k)),
            )
        assert marker.read_text(encoding="utf-8") == "keep me"
        assert existing.exists() and not spawn_calls

        lifecycle = open_lock(root / ".lifecycle.lock")
        try:
            assert lock_file(lifecycle, blocking=False)
        finally:
            lock_file(lifecycle, unlock=True)
            lifecycle.close()
    finally:
        lock_file(owner, unlock=True)
        owner.close()


def test_start_board_uses_existing_healthy_service_without_temp(tmp_path):
    from pyside_gui.board_runtime import start_board

    client, factories = FakeClient([{"version": 1}]), []
    runtime = start_board(
        "http://127.0.0.1:8765", None, state_dir=tmp_path,
        client_factory=lambda *a, **k: client,
        temp_factory=lambda **k: factories.append(k),
    )
    assert runtime.client is client and runtime.temp is None
    assert runtime.central_url is None and runtime.url == "http://127.0.0.1:8765"
    assert [entry[1] for entry in client.registered] == ["agent"]
    assert not factories and not (tmp_path / "user_handle").exists()


def test_main_handle_is_stable_across_starts(tmp_path):
    from pyside_gui.board_runtime import start_board

    handles = []
    for _ in range(2):
        client = FakeClient([{"version": 1}])
        handles.append(start_board(
            "http://127.0.0.1:8765", None, state_dir=tmp_path,
            client_factory=lambda *a, **k: client,
        ).session.handle)
    assert handles[0] == handles[1]
    assert (tmp_path / "main_handle").read_text(encoding="utf-8").strip() == handles[0]


@pytest.mark.parametrize("url", ["http://127.0.0.1:9876", "http://central.lan:9876"])
def test_unreachable_twice_starts_temp_board_without_token(tmp_path, url):
    from pyside_gui.board_runtime import start_board

    central = FakeClient([refused_error(), refused_error()])
    local = FakeClient([{"version": 1}])
    temp = type("Temp", (), {"url": "http://127.0.0.1:49123", "close": lambda self: None})()
    requested, clock = [], Clock()

    def client_factory(target, token, **kwargs):
        requested.append((target, token))
        return central if target == url else local

    runtime = start_board(
        url, "central-token", state_dir=tmp_path, client_factory=client_factory,
        temp_factory=lambda **kwargs: temp, sleep=clock.sleep, clock=clock,
    )
    assert runtime.temp is temp and runtime.url == temp.url and runtime.central_url == url
    assert requested == [(url, "central-token"), (temp.url, None)]
    assert clock.now == 2.0


def test_retry_success_does_not_start_temp(tmp_path):
    from pyside_gui.board_runtime import start_board

    client, temp_calls, clock = FakeClient([refused_error(), {"version": 1}]), [], Clock()
    runtime = start_board(
        "http://central.lan:8765", "secret", state_dir=tmp_path,
        client_factory=lambda *a, **k: client,
        temp_factory=lambda **k: temp_calls.append(1), sleep=clock.sleep, clock=clock,
    )
    assert runtime.central_url is None and not temp_calls and clock.now == 2.0


@pytest.mark.parametrize("error", [BoardError("UNAUTHORIZED", "bad token"),
                                    BoardError("NOT_A_BOARD", "foreign")])
def test_auth_or_foreign_service_never_starts_temp(tmp_path, error):
    from pyside_gui.board_runtime import start_board

    calls = []
    with pytest.raises(BoardError):
        start_board(
            "http://central.lan:8765", None, state_dir=tmp_path,
            client_factory=lambda *a, **k: FakeClient([error]),
            temp_factory=lambda **k: calls.append(1),
        )
    assert not calls


@pytest.mark.parametrize("outcome", [
    BoardError("INVALID_RESPONSE", "bad JSON"), BoardError("HTTP_404", "missing"),
    ValueError("wrong shape"),
])
def test_malformed_or_foreign_health_maps_to_not_a_board(tmp_path, outcome):
    from pyside_gui.board_runtime import start_board

    client, calls = FakeClient([outcome]), []
    with pytest.raises(BoardError) as caught:
        start_board(
            "http://127.0.0.1:8765", None, state_dir=tmp_path,
            client_factory=lambda *a, **k: client,
            temp_factory=lambda **k: calls.append("temp"),
        )
    assert caught.value.code == "NOT_A_BOARD" and client.closed and not calls


def test_invalid_service_root_fails_before_client_or_temp_factory(tmp_path):
    from pyside_gui.board_runtime import start_board

    calls = []
    with pytest.raises(BoardError) as caught:
        start_board(
            "http://127.0.0.1:8765/path?x=1", None, state_dir=tmp_path,
            client_factory=lambda *a, **k: calls.append("client"),
            temp_factory=lambda **k: calls.append("temp"),
        )
    assert caught.value.code == "NOT_A_BOARD" and calls == []


def test_cancelled_retry_does_not_start_temp(tmp_path):
    from pyside_gui.board_runtime import start_board

    cancel, calls = threading.Event(), []
    client = FakeClient([refused_error(), refused_error()])
    with pytest.raises(BoardError, match="cancelled"):
        start_board(
            "http://central.lan:8765", None, state_dir=tmp_path,
            client_factory=lambda *a, **k: client,
            temp_factory=lambda **k: calls.append(1),
            sleep=lambda _seconds: cancel.set(), cancel=cancel,
        )
    assert client.closed and not calls


def test_failure_after_temp_start_closes_temp(tmp_path):
    from pyside_gui.board_runtime import start_board

    central = FakeClient([refused_error(), refused_error()])
    local = FakeClient([{"version": 1}])

    class Temp:
        url = "http://127.0.0.1:49123"
        closed = 0

        def close(self):
            self.closed += 1

    temp = Temp()
    local.register = lambda *a, **k: (_ for _ in ()).throw(BoardError("HANDLE_TAKEN", "conflict"))
    with pytest.raises(BoardError, match="conflict"):
        start_board(
            "http://central.lan:8765", None, state_dir=tmp_path,
            client_factory=lambda target, *a, **k: local if target == temp.url else central,
            temp_factory=lambda **k: temp, sleep=lambda _seconds: None,
        )
    assert temp.closed == 1 and local.closed


def test_temp_board_lifecycle_live(tmp_path):
    from pyside_gui.board_runtime import TempBoard

    temp = TempBoard.start(root=tmp_path / "temp", wait_s=10)
    run_dir, url, process = temp.run_dir, temp.url, temp.process
    client = BoardClient(url, timeout=1)
    try:
        assert client.health()["version"] == 1
        record = json.loads(next((run_dir / "run").glob("board-*.json")).read_text())
        assert url.endswith(f":{record['port']}") and record["port"] != 0
    finally:
        client.close()
        temp.close()
    assert process.poll() is not None and not run_dir.exists()
    temp.close()  # idempotent


def test_temp_board_exits_when_parent_pipe_closes(tmp_path):
    from pyside_gui.board_runtime import TempBoard

    temp = TempBoard.start(root=tmp_path / "temp", wait_s=10)
    process = temp.process
    process.stdin.close()
    process.wait(timeout=5)
    temp.close()
    assert process.poll() is not None and not temp.run_dir.exists()


def test_sweep_stale_removes_only_unlocked_runs(tmp_path):
    from services.message_board.runtime_records import lock_file, open_lock
    from pyside_gui.board_runtime import sweep_stale

    root = tmp_path / "temp"
    stale, active = root / "stale", root / "active"
    stale.mkdir(parents=True)
    active.mkdir()
    owner = open_lock(active / "owner.lock")
    assert lock_file(owner, blocking=False)
    try:
        sweep_stale(root)
        assert not stale.exists() and active.exists()
    finally:
        lock_file(owner, unlock=True)
        owner.close()


def test_runtime_record_discovery_and_nonblocking_lock(tmp_path):
    from services.message_board.runtime_records import (
        discover_record, lock_file, open_lock, write_record,
    )

    runtime_dir = tmp_path / "run"
    expected = {"url": "http://127.0.0.1:41234", "port": 41234,
                "instance_id": "a" * 32, "capability": "b" * 64}
    write_record(runtime_dir, expected)
    assert discover_record(runtime_dir) == expected
    first, second = open_lock(tmp_path / "owner.lock"), open_lock(tmp_path / "owner.lock")
    try:
        assert lock_file(first, blocking=False)
        assert not lock_file(second, blocking=False)
    finally:
        lock_file(first, unlock=True)
        first.close()
        second.close()


def test_concurrent_start_cannot_sweep_new_owned_run(tmp_path):
    from pyside_gui.board_runtime import TempBoard

    root = tmp_path / "temp"
    results, errors = [], []

    def start():
        try:
            results.append(TempBoard.start(root=root, wait_s=10))
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    try:
        assert not errors and len(results) == 2
        assert all(item.run_dir.exists() and item.process.poll() is None for item in results)
    finally:
        for item in results:
            item.close()


def test_parse_sse_ignores_ping_and_combines_split_data():
    from pyside_gui.board_runtime import parse_sse

    lines = [": ping", "", "event: post", 'data: {"id": 1,',
             'data: "text": "one"}', "", "event: other", 'data: {"id": 9}', "",
             "event: post", 'data: {"id": 2, "text": "two"}', ""]
    assert list(parse_sse(lines)) == [{"id": 1, "text": "one"}, {"id": 2, "text": "two"}]


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

    @contextmanager
    def stream(self, after=None):
        self.after.append(after)
        item = next(self.streams)
        if isinstance(item, BaseException):
            raise item
        try:
            yield item
        finally:
            item.close()


def test_listener_reconnects_and_dedupes_overlapping_posts():
    from pyside_gui.board_runtime import StreamListener

    replay = ClosableLines(["event: post", 'data: {"id": 2}', "",
                            "event: post", 'data: {"id": 3}', ""])
    client = StreamClient([BoardError("UNREACHABLE", "reset"), replay])
    posts, statuses, listener = [], [], None

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

    entered = threading.Event()
    lines = ClosableLines([], block=entered)
    listener = StreamListener(StreamClient([lines]), 0, lambda post: None, lambda status: None)
    listener.start()
    assert entered.wait(1)
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
