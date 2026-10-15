"""Board SSE iterator is authenticated, relative and actively closable."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import httpx
import pytest

from agent.board_client import BoardClient, BoardError


def test_stream_relative_cursor_auth_and_response_closure():
    responses = []
    def handler(request):
        assert request.url.path == "/stream" and request.url.params["after"] == "4"
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.headers["Connection"] == "close"
        response = httpx.Response(200, stream=httpx.ByteStream(b"id: 5\ndata: hello\n\n"))
        responses.append(response)
        return response
    with httpx.Client(base_url="http://board", transport=httpx.MockTransport(handler)) as http:
        board = BoardClient("http://board", token="secret", http=http)
        with board.stream(4) as lines:
            assert list(lines) == ["id: 5", "data: hello", ""]
            assert callable(lines.close)
    assert responses[0].is_closed


def test_stream_error_has_code_and_cause():
    with httpx.Client(base_url="http://board", transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={
                "code": "UNAUTHORIZED", "error": "token",
            }))) as http:
        with pytest.raises(BoardError) as caught:
            with BoardClient("http://board", http=http).stream():
                raise AssertionError("unauthorized stream must not open")
        assert caught.value.code == "UNAUTHORIZED" and caught.value.__cause__ is not None


def test_close_interrupts_real_blocked_sse_read():
    finish, reading = threading.Event(), threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: ready\n\n")
            self.wfile.flush()
            finish.wait(5)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    board = BoardClient(f"http://127.0.0.1:{server.server_port}")
    try:
        with board.stream() as lines, ThreadPoolExecutor(max_workers=1) as pool:
            assert next(lines) == "data: ready" and next(lines) == ""
            def next_line():
                reading.set()
                return next(lines, None)
            pending = pool.submit(next_line)
            assert reading.wait(1)
            threading.Event().wait(.05)
            assert not pending.done()
            lines.close()
            assert pending.result(timeout=1) is None
    finally:
        finish.set()
        board.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_finished_stream_never_interrupts_returned_pooled_socket():
    class SocketSentinel:
        def shutdown(self, how):
            raise AssertionError("completed response returned this socket to its connection pool")
    class Network:
        def get_extra_info(self, name):
            assert name == "socket"
            return SocketSentinel()
    def handler(request):
        return httpx.Response(200, stream=httpx.ByteStream(b"data: done\n\n"),
                              extensions={"network_stream": Network()})
    with httpx.Client(base_url="http://board", transport=httpx.MockTransport(handler)) as http:
        with BoardClient("http://board", http=http).stream() as lines:
            assert list(lines) == ["data: done", ""]


_PURGE_LINES = [
    "event: post", 'data: {"id": 1, "author": "a"}', "",
    "event: purge", 'data: {"id": 1, "scope": "all", "through": 1, "created_at": "t"}', "",
    ": ping", "",
    "event: purge", 'data: {"id": 2, "scope": "author", "author": "b", "through": 3}', "",
    "event: purge", "data: [1, 2]", "",
    "event: post", 'data: {"id": 4, "author": "c"}', "",
]


def test_parse_sse_events_yields_posts_and_purges_in_order():
    from pyside_gui.board_stream import parse_sse_events

    assert list(parse_sse_events(_PURGE_LINES)) == [
        ("post", {"id": 1, "author": "a"}),
        ("purge", {"id": 1, "scope": "all", "through": 1, "created_at": "t"}),
        ("purge", {"id": 2, "scope": "author", "author": "b", "through": 3}),
        ("post", {"id": 4, "author": "c"}),
    ]


def test_parse_sse_still_yields_only_posts():
    from pyside_gui.board_stream import parse_sse

    assert list(parse_sse(_PURGE_LINES)) == [{"id": 1, "author": "a"}, {"id": 4, "author": "c"}]


class _Lines:
    def __init__(self, lines):
        self._lines = iter(lines)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._lines)

    def close(self):
        pass


class _OneStream:
    def __init__(self, lines):
        self.lines = lines
        self.after = []

    def stream(self, after=None):
        from contextlib import nullcontext
        self.after.append(after)
        return nullcontext(_Lines(self.lines))


def test_listener_forwards_purges_without_advancing_after():
    from pyside_gui.board_stream import StreamListener

    purge = {"id": 7, "scope": "all", "through": 50, "created_at": "t"}
    client = _OneStream(["event: purge", 'data: {"id": 7, "scope": "all", "through": 50, '
                         '"created_at": "t"}', ""])
    posts, purges = [], []
    listener = StreamListener(client, 3, posts.append, lambda status: None,
                              on_purge=purges.append)
    assert listener._listen_once() is False  # a replayed purge is not new delivery
    assert purges == [purge] and posts == [] and listener.after == 3


def test_listener_without_purge_callback_ignores_purges_and_keeps_posts():
    from pyside_gui.board_stream import StreamListener

    client = _OneStream(["event: purge", 'data: {"id": 7, "scope": "all", "through": 50}', "",
                         "event: post", 'data: {"id": 4}', ""])
    posts = []
    listener = StreamListener(client, 3, posts.append, lambda status: None)
    assert listener._listen_once() is True
    assert posts == [{"id": 4}] and listener.after == 4
