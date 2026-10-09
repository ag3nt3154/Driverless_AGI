"""SQLite board store contract (spec §5)."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.message_board.blobs import sanitize_name, sniff_kind, sniff_mime
from services.message_board.store import (
    MAX_ATTACHMENT, BoardStore, StoreError, extract_mentions,
)

A, B = "main_3f9a1c2e", "researcher_9b21c0de"


@pytest.fixture
def store(tmp_path):
    board = BoardStore(tmp_path / "board.sqlite3")
    board.register_member(A, "agent", host="pc")
    board.register_member(B, "agent", host="pc")
    yield board
    board.close()


def fails(code, call, status=None):
    with pytest.raises(StoreError) as caught:
        call()
    assert caught.value.code == code
    if status is not None:
        assert caught.value.status == status


def test_member_registration(store, monkeypatch):
    monkeypatch.setattr("services.message_board.store._now", lambda: "2026-10-09T00:00:00Z")
    member, created = store.register_member(A, "agent", host="pc")
    assert not created and member["last_seen"] == "2026-10-09T00:00:00Z"
    assert member["display_name"] == A
    fails("HANDLE_TAKEN", lambda: store.register_member(A, "user", host="pc"), 409)
    fails("HANDLE_TAKEN", lambda: store.register_member(A, "agent", host="other"), 409)
    fails("INVALID", lambda: store.register_member("new_00000000", "bot"), 422)
    assert [m["handle"] for m in store.list_members()] == [A, B]


@pytest.mark.parametrize("handle", ["Main_3f9a1c2e", "main_3f9a1c2", "main", "_3f9a1c2e",
                                    "x" * 33 + "_3f9a1c2e", "main_3f9a1c2e\n"])
def test_bad_handle(store, handle):
    fails("INVALID", lambda: store.register_member(handle, "agent"), 422)


@pytest.mark.parametrize("kwargs,code", [
    ({"author": "ghost_00000000", "text": "hi"}, "UNKNOWN_AUTHOR"),
    ({"author": A, "text": ""}, "INVALID"),
    ({"author": A, "text": "x" * 701}, "INVALID"),
    ({"author": A, "text": "hi", "meme": "m" * 65}, "INVALID"),
    ({"author": A, "text": "hi", "reply_to": 999}, "UNKNOWN_POST"),
    ({"author": A, "text": "hi", "reply_to": 2**63}, "INVALID"),
    ({"author": A, "text": "hi", "reply_to": True}, "INVALID"),
])
def test_post_validation(store, kwargs, code):
    fails(code, lambda: store.create_post(**kwargs))
    assert store.latest_id() == 0


def test_mentions_and_post_shape(store, monkeypatch):
    text = f"@{B} @{A}, @{B}; @Bad_1234 @main @{A}X @{B}-extra"
    assert extract_mentions(text) == [B, A]
    monkeypatch.setattr("services.message_board.store._now", lambda: "2026-10-09T00:00:00Z")
    post = store.create_post(author=A, text="x" * 700, meme="m" * 64)
    assert post == dict(id=1, board="default", author=A, text="x" * 700, mentions=[],
                        meme="m" * 64, reply_to=None, attachments=[],
                        created_at="2026-10-09T00:00:00Z")
    assert store.list_members()[0]["last_seen"] == post["created_at"]
    assert store.create_post(author=B, text="reply", reply_to=1)["reply_to"] == 1


def test_reads(store):
    for i in range(5):
        store.create_post(author=A, text=f"p{i}" + (f" @{B}" if i % 2 else ""))
    assert [p["id"] for p in store.list_posts(after=3)] == [4, 5]
    assert [p["id"] for p in store.list_posts(limit=2)] == [4, 5]
    assert [p["id"] for p in store.list_posts(mention=B, limit=1)] == [4]
    assert [p["id"] for p in store.list_posts(mention=B, after=0, limit=1)] == [2]
    assert store.list_posts(after=2**63 - 1) == []
    for kwargs in ({"after": -1}, {"limit": 0}, {"limit": 201}, {"after": True}):
        fails("INVALID", lambda: store.list_posts(**kwargs), 422)


def test_reopen(tmp_path):
    path = tmp_path / "board.sqlite3"
    board = BoardStore(path)
    board.register_member(A, "agent")
    att = board.add_attachment(A, "hello.txt", b"hello")
    board.create_post(author=A, text="one", attachments=[att["id"]])
    board.close()
    reopened = BoardStore(path)
    try:
        assert reopened.create_post(author=A, text="two")["id"] == 2
        assert reopened.get_attachment(att["id"])[1].read_bytes() == b"hello"
        assert reopened.list_posts()[0]["attachments"] == [att]
    finally:
        reopened.close()


@pytest.mark.parametrize("head,mime", [
    (b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"),
    (b"RIFF1234WEBP", "image/webp"),
])
def test_sniff_images(head, mime):
    assert sniff_kind(head) == "image"
    assert sniff_mime(head, "wrong.txt") == mime


def test_sniff_file():
    assert sniff_kind(b"text") == "file"
    assert sniff_kind(b"RIFF1234WAVE") == "file"
    assert sniff_mime(b"text", "a.txt") == "text/plain"
    assert sniff_mime(b"text", "a.unknown-extension") == "application/octet-stream"


@pytest.mark.parametrize("name,expected", [
    ("..\\..\\evil.exe", "evil.exe"), ("../../evil.exe", "evil.exe"),
    ("a:b*c", "a_b_c"), ("", "file"), (".", "file"), ("..", "file"),
    ("hello.  ", "hello"), ("CON", "_CON"), ("NUL.txt", "_NUL.txt"),
    ("COM1", "_COM1"), ("LPT9", "_LPT9"), ("con.txt", "_con.txt"),
    ("a\x00\x7fb", "a__b"), ("x" * 130, "x" * 128),
])
def test_names(name, expected):
    assert sanitize_name(name) == expected


def test_attachment_dedupe_and_metadata(store, tmp_path):
    one = store.add_attachment(A, "fake.png", b"plain text")
    two = store.add_attachment(A, "two.txt", b"plain text")
    assert one["id"] != two["id"] and one["sha256"] == two["sha256"]
    assert one["kind"] == "file" and one["size"] == 10
    assert len(list((tmp_path / "blobs").iterdir())) == 1
    meta, path = store.get_attachment(one["id"])
    assert meta == one and path.read_bytes() == b"plain text"
    assert "post_id" not in meta and "path" not in meta
    post = store.create_post(author=A, text="attached", attachments=[two["id"], one["id"]])
    assert {a["id"] for a in post["attachments"]} == {one["id"], two["id"]}
    assert store.list_posts()[0] == post


def test_attachment_errors_and_rollback(store):
    fails("UNKNOWN_AUTHOR", lambda: store.add_attachment("ghost_00000000", "a", b"a"), 404)
    fails("INVALID", lambda: store.add_attachment(A, "a", b""), 422)
    fails("TOO_LARGE", lambda: store.add_attachment(A, "a", b"x" * (MAX_ATTACHMENT + 1)), 413)
    fails("UNKNOWN_ATTACHMENT", lambda: store.get_attachment("att_000000000000"), 404)
    att = store.add_attachment(A, "a", b"a")["id"]
    fails("INVALID", lambda: store.create_post(author=A, text="x", attachments=[att] * 5))
    fails("INVALID", lambda: store.create_post(author=A, text="x", attachments=[att, att]))
    fails("INVALID", lambda: store.create_post(author=B, text="x", attachments=[att]))
    fails("UNKNOWN_ATTACHMENT", lambda: store.create_post(
        author=A, text="x", attachments=[att, "att_000000000000"]))
    assert store.latest_id() == 0
    store.create_post(author=A, text="x", attachments=[att])
    fails("ATTACHMENT_USED", lambda: store.create_post(
        author=A, text="x", attachments=[att]), 409)
    assert store.latest_id() == 1


def test_concurrent_attachment_claims_are_atomic(store, tmp_path):
    other = BoardStore(tmp_path / "board.sqlite3")
    att = store.add_attachment(A, "a", b"a")["id"]

    def claim(board):
        try:
            return board.create_post(author=A, text="claim", attachments=[att])["id"]
        except StoreError as error:
            return error.code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, [store, other]))
        assert sorted(map(str, results)) == ["1", "ATTACHMENT_USED"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(
                lambda i: store.create_post(author=A, text=str(i))["id"], range(20)))
        assert len(set(ids)) == 20 and store.latest_id() == 21
    finally:
        other.close()


def test_write_failure_rolls_back_post_and_claim(store, monkeypatch):
    import sqlite3

    att = store.add_attachment(A, "a", b"a")["id"]
    original = store._post_row

    def fail_render(row):
        raise sqlite3.OperationalError("injected failure after writes")

    monkeypatch.setattr(store, "_post_row", fail_render)
    with pytest.raises(sqlite3.OperationalError, match="injected failure"):
        store.create_post(author=A, text=f"ping @{B}", attachments=[att])
    assert store.latest_id() == 0
    assert store.list_posts(mention=B) == []
    monkeypatch.setattr(store, "_post_row", original)
    assert store.create_post(author=A, text="retry", attachments=[att])["id"] == 1


def test_exact_attachment_limit(store):
    attachment = store.add_attachment(A, "max.bin", b"x" * MAX_ATTACHMENT)
    assert attachment["size"] == MAX_ATTACHMENT
