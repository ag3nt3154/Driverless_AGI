"""Multipart receive bounds and early-abort guarantees."""
import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect, Request

from services.message_board.app import create_app
from services.message_board.store import MAX_ATTACHMENT, BoardStore, StoreError
from services.message_board.uploads import MAX_BODY, receive_upload

A = "main_3f9a1c2e"
HEADER = b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\n'
TRAILER = (b'\r\n--x\r\nContent-Disposition: form-data; name="uploader"\r\n\r\n'
           + A.encode() + b'\r\n--x--\r\n')


def consume(chunks, *, length=None, disconnect=False):
    """Return outcome and receive count, with a poison receive after supplied chunks."""
    calls = []
    headers = [(b"content-type", b"multipart/form-data; boundary=x")]
    if length is not None:
        headers.append((b"content-length", str(length).encode()))
    scope = {"type": "http", "headers": headers}
    async def run():
        async def receive():
            index = len(calls)
            calls.append(index)
            if index == len(chunks) and disconnect:
                return {"type": "http.disconnect"}
            if index >= len(chunks):
                raise AssertionError("upload drained another chunk after it should have stopped")
            return {"type": "http.request", "body": chunks[index],
                    "more_body": index < len(chunks) - 1 or disconnect}
        try:
            return await receive_upload(Request(scope, receive))
        except (StoreError, ClientDisconnect) as error:
            return error
    return asyncio.run(run()), calls


def test_file_limit_without_content_length_aborts_first_violating_chunk():
    chunks = [HEADER, b"x" * MAX_ATTACHMENT, b"x" + TRAILER, b"poison"]
    outcome, calls = consume(chunks)
    assert isinstance(outcome, StoreError) and outcome.code == "TOO_LARGE"
    assert len(calls) == 3


def test_total_body_limit_and_declared_limit():
    outcome, calls = consume([b"poison"], length=MAX_BODY + 1)
    assert outcome.code == "TOO_LARGE" and calls == []
    outcome, calls = consume([HEADER, b"x" * MAX_BODY, b"poison"])
    assert outcome.code == "TOO_LARGE" and len(calls) == 2
    outcome, calls = consume([HEADER + b"ok" + TRAILER], length=MAX_BODY)
    assert outcome == (A, "a.txt", b"ok")
    outcome, calls = consume([b"poison"], length="bad")
    assert outcome.code == "INVALID" and not calls


def test_exact_file_limit_and_empty_file():
    outcome, _ = consume([HEADER, b"x" * MAX_ATTACHMENT, TRAILER])
    assert outcome[0:2] == (A, "a.txt") and len(outcome[2]) == MAX_ATTACHMENT


@pytest.mark.parametrize("part,code", [
    (b'--x\r\nContent-Disposition: form-data; name="uploader"\r\n\r\n' + b"a" * 129,
     "TOO_LARGE"),
    (b'--x\r\nX-Long: ' + b"x" * 8193, "TOO_LARGE"),
    (b'--x\r\nContent-Disposition: form-data; name="other"\r\n\r\n', "INVALID"),
    (b'--x\r\nContent-Disposition: form-data; name="file"\r\n\r\n', "INVALID"),
    (b'--x\r\nContent-Disposition: form-data; name="uploader"; filename="x"\r\n\r\n',
     "INVALID"),
], ids=["field", "headers", "extra", "no-filename", "uploader-file"])
def test_bounded_headers_fields_and_invalid_parts(part, code):
    outcome, calls = consume([part, b"poison"])
    assert isinstance(outcome, StoreError) and outcome.code == code, repr(outcome)
    assert calls == [0]


def test_duplicate_extra_incomplete_and_disconnect():
    duplicate = (HEADER + b"ok\r\n" + HEADER + b"again" + TRAILER)
    outcome, _ = consume([duplicate])
    assert outcome.code == "INVALID"
    outcome, _ = consume([HEADER + b"incomplete"])
    assert outcome.code == "INVALID"
    outcome, calls = consume([HEADER + b"partial"], disconnect=True)
    assert isinstance(outcome, ClientDisconnect) and len(calls) == 2


def test_endpoint_rejected_uploads_do_not_persist(tmp_path):
    store = BoardStore(tmp_path / "b.sqlite3")
    store.register_member(A, "agent")
    try:
        with TestClient(create_app(store)) as client:
            for content, expected in ((b"", 422), (b"x" * (MAX_ATTACHMENT + 1), 413)):
                response = client.post("/attachments", data={"uploader": A},
                                       files={"file": ("a.txt", content)})
                assert response.status_code == expected
                assert response.headers["x-content-type-options"] == "nosniff"
            assert not (tmp_path / "blobs").exists()
            assert store._conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    finally:
        store.close()


def test_aggregate_header_whitespace_budget_and_chunk_boundaries():
    headers = (b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n'
               + b'X-One:' + b' ' * 4100 + b'a\r\n'
               + b'X-Two:' + b' ' * 4100 + b'b\r\n\r\n')
    outcome, calls = consume([headers, b"poison"])
    assert outcome.code == "TOO_LARGE" and calls == [0]
    complete = HEADER + b"ok" + TRAILER
    for chunk_size in (1, 2, 3, 7, 50):
        chunks = [complete[i:i + chunk_size] for i in range(0, len(complete), chunk_size)]
        outcome, _ = consume(chunks)
        assert outcome == (A, "a.txt", b"ok")


def test_exact_body_overhead_and_header_bounds():
    complete = HEADER + b"ok" + TRAILER
    padding = b"\r\n" * ((MAX_BODY - len(complete)) // 2)
    padding += b"\r" * (MAX_BODY - len(complete) - len(padding))
    outcome, _ = consume([complete, padding])
    assert outcome == (A, "a.txt", b"ok")
    outcome, calls = consume([complete, padding, b"x", b"poison"])
    assert outcome.code == "TOO_LARGE" and len(calls) == 3
    base = HEADER[:-2] + b"X-Padding: "
    header = base + b"x" * (8192 - len(base) + len(b"--x\r\n") - 4) + b"\r\n\r\n"
    outcome, _ = consume([header + b"ok" + TRAILER])
    assert outcome == (A, "a.txt", b"ok")
    outcome, calls = consume([header.replace(b"X-Padding: ", b"X-Padding: x"), b"poison"])
    assert outcome.code == "TOO_LARGE" and calls == [0]
