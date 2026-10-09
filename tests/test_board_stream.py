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
