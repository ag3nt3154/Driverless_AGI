"""Board HTTP client and per-agent cursor contract."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.board_client import BoardClient, BoardError, BoardSession, new_handle
from services.message_board.app import create_app
from services.message_board.store import BoardStore

A, B = "main_3f9a1c2e", "other_1234abcd"


@pytest.fixture
def client(tmp_path):
    store = BoardStore(tmp_path / "server" / "board.sqlite3")
    app = create_app(store)
    with TestClient(app) as http:
        board = BoardClient("http://board", http=http, download_http=lambda: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://board"))
        board.register(A, "agent")
        board.register(B, "agent")
        yield board
    store.close()


def test_roundtrip_and_errors(client):
    assert client.health()["status"] == "ok"
    assert len(client.members()) == 2
    post = client.post(A, "hello")
    assert client.posts(after=0) == [post]
    with pytest.raises(BoardError) as caught:
        client.post("ghost_00000000", "hi")
    assert caught.value.code == "UNKNOWN_AUTHOR"


def test_session_independent_cursors_and_serialized_reads(client):
    session = BoardSession(client, A)
    for i in range(5):
        client.post(B, str(i) + (f" @{A}" if i == 2 else ""))
    assert [p["id"] for p in session.read(limit=2, mentions_only=True)] == [3]
    assert [p["id"] for p in session.read(limit=2)] == [4, 5]
    assert session.read() == []
    client.post(B, "six")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: session.read(), range(2)))
    assert sorted(len(items) for items in results) == [0, 1]
    assert session.read(mentions_only=True) == []


def test_handles():
    assert re.fullmatch(r"hello-world_[0-9a-f]{8}", new_handle("hello-world"))
    for bad in ("", "Upper", "x" * 33, "bad_name", "-start"):
        with pytest.raises(ValueError):
            new_handle(bad)


def test_fetch_roundtrip_cache_and_session(client, tmp_path):
    source = tmp_path / "input.txt"
    source.write_bytes(b"hello")
    session = BoardSession(client, A)
    post = session.post("uploaded", files=[source])
    attachment = post["attachments"][0]
    meta, path = session.fetch(attachment["id"], tmp_path / "project")
    assert meta == attachment and path.read_bytes() == b"hello"
    assert path == tmp_path / "project" / ".dagi/board/attachments" / meta["id"] / meta["name"]
    assert client.fetch_attachment(meta["id"], project_root=tmp_path / "project")[1] == path
    path.write_bytes(b"wrong")
    client.fetch_attachment(meta["id"], project_root=tmp_path / "project")
    assert path.read_bytes() == b"hello"
    assert list(path.parent.iterdir()) == [path]


def metadata(**changes):
    return {"id": "att_123456abcdef", "name": "hello.txt", "size": 5,
            "sha256": hashlib.sha256(b"hello").hexdigest(), "kind": "file", **changes}


def mock_download(handler):
    return BoardClient("http://board", download_http=lambda: httpx.AsyncClient(
        base_url="http://board", transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("changes", [
    {"name": "../evil"}, {"name": "..\\evil"}, {"name": "/abs"}, {"name": "C:evil"},
    {"name": "C:\\evil"}, {"name": "\\\\host\\share"}, {"name": "."}, {"name": ".."},
    {"name": "NUL.txt"}, {"name": "CON"}, {"name": "lpt9.log"}, {"name": "COM1"},
    {"name": "trailing."}, {"name": "trailing "}, {"name": "bad\x00.txt"}, {"name": ""},
    {"name": "x" * 129}, {"id": "att_000000000000"}, {"size": 0}, {"size": True},
    {"size": 10 * 1024 * 1024 + 1}, {"sha256": "A" * 64}, {"sha256": "x"},
    {"kind": "script"},
])
def test_invalid_metadata_rejected_before_cache_creation(tmp_path, changes):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=metadata(**changes))
    board = mock_download(handler)
    with pytest.raises(BoardError) as caught:
        board.fetch_attachment(metadata()["id"], project_root=tmp_path)
    assert caught.value.code == "INVALID_ATTACHMENT"
    assert isinstance(caught.value.__cause__, ValueError)
    assert not (tmp_path / ".dagi").exists() and len(calls) == 1


@pytest.mark.parametrize("bad", ["att_ABCDEF123456", "../bad", "att_12", None])
def test_bad_requested_id_never_calls_http(tmp_path, bad):
    def handler(request):
        raise AssertionError("invalid id must fail before HTTP")
    with pytest.raises(BoardError) as caught:
        mock_download(handler).fetch_attachment(bad, project_root=tmp_path)
    assert caught.value.code == "INVALID_ATTACHMENT"


@pytest.mark.parametrize("component", [".dagi", ".dagi/board", ".dagi/board/attachments",
                                       ".dagi/board/attachments/att_123456abcdef",
                                       ".dagi/board/attachments/att_123456abcdef/hello.txt"])
def test_existing_symlink_cache_escape(tmp_path, component, monkeypatch):
    project, outside = tmp_path / "project", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    target = project / component
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix:
        destination = outside / "hello.txt"
        destination.write_bytes(b"safe outside")
        make_cache_link(target, destination, False, monkeypatch)
    else:
        make_cache_link(target, outside, True, monkeypatch)
    board = mock_download(lambda request: httpx.Response(200, json=metadata()))
    with pytest.raises(BoardError) as caught:
        BoardSession(board, A).fetch(metadata()["id"], project)
    assert caught.value.code == "INVALID_ATTACHMENT"
    assert list(outside.iterdir()) == ([destination] if target.suffix else [])


def test_existing_windows_junction_rejected(tmp_path):
    import os
    import subprocess
    if os.name != "nt":
        pytest.skip("Windows junction contract")
    project, outside = tmp_path / "project", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    link = project / ".dagi"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                            capture_output=True, timeout=5)
    assert result.returncode == 0
    try:
        board = mock_download(lambda request: httpx.Response(200, json=metadata()))
        with pytest.raises(BoardError) as caught:
            board.fetch_attachment(metadata()["id"], project_root=project)
        assert caught.value.code == "INVALID_ATTACHMENT" and not list(outside.iterdir())
    finally:
        link.rmdir()


def test_download_cache_reuse_and_invalid_bytes_preserve_old_file(tmp_path):
    from agent._board_files import attachment_cache_path
    requests = []
    content = [b"hello"]
    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/meta"):
            return httpx.Response(200, json=metadata())
        return httpx.Response(200, content=content[0])
    board = mock_download(handler)
    att, path = board.fetch_attachment(metadata()["id"], project_root=tmp_path)
    board.fetch_attachment(att["id"], project_root=tmp_path)
    assert requests.count(f"/attachments/{att['id']}") == 1
    assert attachment_cache_path(tmp_path, att) == path
    path.write_bytes(b"old")
    for bad in (b"bad", b"wrong", b"too many bytes"):
        content[0] = bad
        with pytest.raises(BoardError) as caught:
            board.fetch_attachment(att["id"], project_root=tmp_path)
        assert caught.value.code == "INVALID_ATTACHMENT"
        assert path.read_bytes() == b"old" and list(path.parent.iterdir()) == [path]


def test_concurrent_fetches_use_distinct_temporary_files(tmp_path, monkeypatch):
    import threading
    import agent.board_client as module
    barrier, names = threading.Barrier(2), []
    original = module.tempfile.NamedTemporaryFile
    def create(*args, **kwargs):
        file = original(*args, **kwargs)
        names.append(file.name)
        barrier.wait(timeout=5)
        return file
    monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", create)
    def handler(request):
        if request.url.path.endswith("/meta"):
            return httpx.Response(200, json=metadata())
        return httpx.Response(200, content=b"hello")
    board = mock_download(handler)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: board.fetch_attachment(
            metadata()["id"], project_root=tmp_path), range(2)))
    assert len(set(names)) == 2
    assert results[0][1] == results[1][1] and results[0][1].read_bytes() == b"hello"
    assert list(results[0][1].parent.iterdir()) == [results[0][1]]


def test_http_errors_and_preserved_network_causes(tmp_path):
    for error, code in ((httpx.ConnectError("DNS failed"), "UNREACHABLE"),
                        (httpx.ReadTimeout("slow"), "TIMEOUT")):
        def handler(request):
            raise error
        with httpx.Client(base_url="http://board", transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(BoardError) as caught:
                BoardClient("http://board", http=http).health()
        assert caught.value.code == code and caught.value.__cause__ is error
    for response, code in ((httpx.Response(401, json={"error": "token", "code": "UNAUTHORIZED"}),
                            "UNAUTHORIZED"), (httpx.Response(502, text="bad gateway"), "HTTP_502"),
                           (httpx.Response(200, text="not json"), "INVALID_RESPONSE")):
        with httpx.Client(base_url="http://board", transport=httpx.MockTransport(
                lambda request: response)) as http:
            with pytest.raises(BoardError) as caught:
                BoardClient("http://board", http=http).members()
        assert caught.value.code == code and caught.value.__cause__ is not None


def test_real_refused_connection_preserves_cause():
    board = BoardClient("http://127.0.0.1:9", timeout=3)
    try:
        with pytest.raises(BoardError) as caught:
            board.health()
        assert caught.value.code == "UNREACHABLE"
        assert isinstance(caught.value.__cause__, httpx.ConnectError)
    finally:
        board.close()


@pytest.mark.parametrize("stage", [
    "metadata-headers", "metadata-body", "blob-headers", "blob-body",
])
def test_total_deadline_covers_every_network_phase(tmp_path, stage):
    import asyncio
    import time
    closed = []
    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(.01)
                yield b" "
        async def aclose(self):
            closed.append(True)
    async def handler(request):
        is_meta = request.url.path.endswith("/meta")
        target = is_meta == stage.startswith("metadata")
        if target and stage.endswith("headers"):
            await asyncio.sleep(2)
        if target and stage.endswith("body"):
            return httpx.Response(200, stream=Trickle())
        if is_meta:
            return httpx.Response(200, json=metadata())
        return httpx.Response(200, content=b"hello")
    started = time.monotonic()
    with pytest.raises(BoardError) as caught:
        mock_download(handler).fetch_attachment(
            metadata()["id"], project_root=tmp_path, deadline_s=.05)
    assert caught.value.code == "TIMEOUT" and caught.value.__cause__ is not None
    assert time.monotonic() - started < .3
    assert not list(tmp_path.rglob(".download-*"))
    if stage.endswith("body"):
        assert closed


def test_cancel_before_metadata_and_during_body(tmp_path):
    import threading
    cancellation = threading.Event()
    calls, closed = [], []
    class Content(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"h"
            cancellation.set()
            yield b"ello"
        async def aclose(self):
            closed.append(True)
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/meta"):
            return httpx.Response(200, json=metadata())
        return httpx.Response(200, stream=Content())
    board = mock_download(handler)
    cancellation.set()
    with pytest.raises(BoardError) as caught:
        board.fetch_attachment(metadata()["id"], project_root=tmp_path, cancel=cancellation)
    assert caught.value.code == "CANCELLED" and not calls
    cancellation.clear()
    with pytest.raises(BoardError) as caught:
        board.fetch_attachment(metadata()["id"], project_root=tmp_path, cancel=cancellation)
    assert caught.value.code == "CANCELLED" and closed
    assert not list(tmp_path.rglob(".download-*"))
    assert not list(tmp_path.rglob("hello.txt"))


@pytest.mark.parametrize("stage", ["metadata", "blob"])
def test_download_redirects_never_followed(tmp_path, stage):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/meta") and stage == "blob":
            return httpx.Response(200, json=metadata())
        return httpx.Response(302, headers={"Location": "http://elsewhere/secret"})
    with pytest.raises(BoardError) as caught:
        mock_download(handler).fetch_attachment(metadata()["id"], project_root=tmp_path)
    assert caught.value.code == "HTTP_302" and len(calls) == (2 if stage == "blob" else 1)
    assert not list(tmp_path.rglob(".download-*"))


def test_compressed_download_rejected_before_decoding(tmp_path):
    def handler(request):
        if request.url.path.endswith("/meta"):
            return httpx.Response(200, json=metadata())
        return httpx.Response(200, headers={"Content-Encoding": "gzip"},
                              stream=httpx.ByteStream(b"invalid compressed bytes"))
    with pytest.raises(BoardError) as caught:
        mock_download(handler).fetch_attachment(metadata()["id"], project_root=tmp_path)
    assert caught.value.code == "INVALID_ATTACHMENT"
    assert not list(tmp_path.rglob(".download-*"))



def make_cache_link(path, destination, directory, monkeypatch):
    import stat
    import subprocess
    from pathlib import Path
    from types import SimpleNamespace
    try:
        path.symlink_to(destination, target_is_directory=directory)
    except OSError as error:
        if getattr(error, "winerror", None) != 1314:
            raise
        if directory:
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(path), str(destination)],
                                    capture_output=True, timeout=5)
            assert result.returncode == 0, result.stderr
        else:
            # Windows forbids creating a file symlink without developer/admin privilege.
            path.write_bytes(b"placeholder")
            original = Path.lstat
            def symlink_stat(self):
                return SimpleNamespace(st_mode=stat.S_IFLNK) if self == path else original(self)
            monkeypatch.setattr(Path, "lstat", symlink_stat)


@pytest.mark.parametrize("stage", ["metadata", "blob"])
def test_cancellation_interrupts_nonending_network_response(tmp_path, stage):
    import asyncio
    import threading
    import time
    cancellation, closed = threading.Event(), []
    class NeverEnds(httpx.AsyncByteStream):
        async def __aiter__(self):
            cancellation.set()
            while True:
                await asyncio.sleep(.01)
                yield b"h"
        async def aclose(self):
            closed.append(True)
    def handler(request):
        if request.url.path.endswith("/meta") and stage == "blob":
            return httpx.Response(200, json=metadata())
        return httpx.Response(200, stream=NeverEnds())
    started = time.monotonic()
    with pytest.raises(BoardError) as caught:
        mock_download(handler).fetch_attachment(metadata()["id"], project_root=tmp_path,
                                                cancel=cancellation, deadline_s=2)
    assert caught.value.code == "CANCELLED" and closed
    assert time.monotonic() - started < .5
    assert not list(tmp_path.rglob(".download-*"))


def test_token_applied_to_core_and_download_requests(tmp_path):
    store = BoardStore(tmp_path / "server" / "b.sqlite3")
    app = create_app(store, "secret")
    try:
        with TestClient(app) as http:
            with pytest.raises(BoardError) as caught:
                BoardClient("http://board", http=http).members()
            assert caught.value.code == "UNAUTHORIZED"
            board = BoardClient("http://board", token="secret", http=http,
                                download_http=lambda: httpx.AsyncClient(
                                    base_url="http://board",
                                    transport=httpx.ASGITransport(app=app)))
            board.register(A, "agent")
            path = tmp_path / "source.txt"
            path.write_bytes(b"hello")
            attachment = board.upload(A, path)
            _, saved = board.fetch_attachment(attachment["id"], project_root=tmp_path)
            assert saved.read_bytes() == b"hello"
    finally:
        store.close()
