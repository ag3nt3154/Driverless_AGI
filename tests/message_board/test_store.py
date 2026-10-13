"""SQLite board store contract (spec §5)."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from services.message_board.blobs import sanitize_name, sniff_kind, sniff_mime
from services.message_board.store import (
    MAX_ATTACHMENT, BoardStore, StoreError, extract_mentions,
)

A, B = "main_3f9a1c2e", "researcher_9b21c0de"
KEY, OTHER_KEY = "k" * 43, "o" * 43


@pytest.fixture
def store(tmp_path):
    board = BoardStore(tmp_path / "board.sqlite3")
    board.register_member(A, "agent", host="pc", key=KEY)
    board.register_member(B, "agent", host="pc", key=KEY)
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
    member, created = store.register_member(A, "agent", host="pc", key=KEY)
    assert not created and member["last_seen"] == "2026-10-09T00:00:00Z"
    assert member["display_name"] == A
    fails("HANDLE_TAKEN", lambda: store.register_member(A, "user", host="pc", key=KEY), 409)
    fails("HANDLE_TAKEN", lambda: store.register_member(A, "agent", host="pc", key=OTHER_KEY), 409)
    fails("INVALID", lambda: store.register_member("new_00000000", "bot", key=KEY), 422)
    # the key, not the self-reported host, proves ownership; a new host is recorded
    assert store.register_member(A, "agent", host="laptop", key=KEY)[0]["host"] == "laptop"
    assert [m["handle"] for m in store.list_members()] == [A, B]
    assert all("key_hash" not in m for m in store.list_members())


def test_members_are_online_only_while_recently_seen(store, monkeypatch):
    start = datetime(2026, 10, 12, tzinfo=timezone.utc)
    clock = [start]
    monkeypatch.setattr("services.message_board.store._clock", lambda: clock[0])
    store.register_member(A, "agent", host="pc", key=KEY)
    clock[0] = start + timedelta(seconds=60)
    store.register_member(B, "agent", host="pc", key=KEY)  # B's heartbeat; A stays quiet
    assert {m["handle"]: m["online"] for m in store.list_members()} == {A: True, B: True}
    clock[0] = start + timedelta(seconds=91)
    assert {m["handle"]: m["online"] for m in store.list_members()} == {A: False, B: True}
    store.create_post(author=A, text="back")  # posting also counts as being seen
    assert all(m["online"] for m in store.list_members())


@pytest.mark.parametrize("key", [None, "", "short", "k" * 129, "k" * 42 + "!"])
def test_bad_key(store, key):
    fails("INVALID", lambda: store.register_member("new_00000000", "agent", key=key), 422)


def test_authenticate(store):
    store.authenticate(A, KEY)
    fails("FORBIDDEN", lambda: store.authenticate(A, OTHER_KEY), 403)
    fails("FORBIDDEN", lambda: store.authenticate(A, None), 403)
    fails("UNKNOWN_AUTHOR", lambda: store.authenticate("ghost_00000000", KEY), 404)


def test_keyless_member_from_an_old_board_is_claimed_once(tmp_path):
    path = tmp_path / "board.sqlite3"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE members (handle TEXT PRIMARY KEY, display_name TEXT NOT NULL, "
        "kind TEXT NOT NULL, host TEXT NOT NULL, registered_at TEXT NOT NULL, "
        "last_seen TEXT NOT NULL);"
        f"INSERT INTO members VALUES ('{A}','{A}','agent','pc','t','t');")
    old.close()
    board = BoardStore(path)
    try:
        fails("FORBIDDEN", lambda: board.authenticate(A, KEY), 403)  # no key yet: no writes
        assert board.register_member(A, "agent", host="pc", key=KEY)[1] is False
        board.authenticate(A, KEY)
        fails("HANDLE_TAKEN", lambda: board.register_member(A, "agent", key=OTHER_KEY), 409)
        assert board.list_bans() == [] and board.list_purges() == []  # tables added on open
        board.ban(A)
        assert board.list_members()[0]["banned"] is True
    finally:
        board.close()


def test_banning_a_keyless_member_matches_only_its_handle(tmp_path):
    path = tmp_path / "board.sqlite3"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE members (handle TEXT PRIMARY KEY, display_name TEXT NOT NULL, "
        "kind TEXT NOT NULL, host TEXT NOT NULL, registered_at TEXT NOT NULL, "
        "last_seen TEXT NOT NULL);"
        f"INSERT INTO members VALUES ('{A}','{A}','agent','pc','t','t');")
    old.close()
    board = BoardStore(path)
    try:
        board.ban(A)  # no key hash to ban: a NULL must never match another member's key
        fails("BANNED", lambda: board.register_member(A, "agent", key=KEY), 403)
        board.register_member(B, "agent", key=OTHER_KEY)
        board.authenticate(B, OTHER_KEY)
    finally:
        board.close()


@pytest.mark.parametrize("handle", ["Main_3f9a1c2e", "main_3f9a1c2", "main", "_3f9a1c2e",
                                    "x" * 33 + "_3f9a1c2e", "main_3f9a1c2e\n"])
def test_bad_handle(store, handle):
    fails("INVALID", lambda: store.register_member(handle, "agent", key=KEY), 422)


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
                        meme="m" * 64, reply_to=None, attachments=[], author_kind="agent",
                        created_at="2026-10-09T00:00:00Z")
    assert store.list_members()[0]["last_seen"] == post["created_at"]
    assert store.create_post(author=B, text="reply", reply_to=1)["reply_to"] == 1


def test_post_carries_author_kind(store):
    user = "web_12345678"
    store.register_member(user, "user", host="web", key=KEY)
    agent_post = store.create_post(author=A, text="agent")
    user_post = store.create_post(author=user, text="user")
    assert agent_post["author_kind"] == "agent"
    assert user_post["author_kind"] == "user"


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
    board.register_member(A, "agent", key=KEY)
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


def test_ban_blocks_register_post_upload_and_key_reuse(store):
    att = store.add_attachment(A, "a.txt", b"before ban")["id"]
    ban = store.ban(A)
    assert ban["handle"] == A and ban["purge"] is None and ban["created_at"]
    fails("BANNED", lambda: store.register_member(A, "agent", host="pc", key=KEY), 403)
    fails("BANNED", lambda: store.authenticate(A, KEY), 403)
    fails("BANNED", lambda: store.authenticate(A, OTHER_KEY), 403)
    fails("BANNED", lambda: store.create_post(author=A, text="hi"), 403)
    fails("BANNED", lambda: store.create_post(author=A, text="hi", attachments=[att]), 403)
    fails("BANNED", lambda: store.add_attachment(A, "a.txt", b"x"), 403)
    # B shares A's key in the fixture, and a brand-new handle reusing it is refused too
    fails("BANNED", lambda: store.register_member("new_00000000", "agent", key=KEY), 403)
    fails("BANNED", lambda: store.authenticate(B, KEY), 403)  # B already owns the banned key
    store.register_member("new_00000000", "agent", key=OTHER_KEY)
    store.unban(A)
    assert store.register_member(A, "agent", host="pc", key=KEY)[1] is False
    store.authenticate(A, KEY)
    store.add_attachment(A, "b.txt", b"after")
    assert store.create_post(author=A, text="back", attachments=[att])["attachments"]
    store.register_member("new2_00000000", "agent", key=KEY)
    assert store.list_bans() == []


def test_ban_unknown_member_and_unban_unknown_are_404(store):
    fails("UNKNOWN_AUTHOR", lambda: store.ban("ghost_00000000"), 404)
    fails("UNKNOWN_BAN", lambda: store.unban(A), 404)
    store.ban(A)
    store.ban(A)  # banning again replaces the ban
    assert [b["handle"] for b in store.list_bans()] == [A]
    assert set(store.list_bans()[0]) == {"handle", "created_at"}
    store.unban(A)
    fails("UNKNOWN_BAN", lambda: store.unban(A), 404)


def test_clear_all_deletes_history_keeps_members_and_ids_increase(store):
    for i in range(3):
        store.create_post(author=A, text=f"@{B} {i}")
    store.ban(B)
    purge = store.clear_all()
    assert purge["scope"] == "all" and purge["through"] == 3 and "author" not in purge
    assert store.list_posts() == [] and store.list_posts(mention=B) == []
    assert store.latest_id() == 0
    assert [m["handle"] for m in store.list_members()] == [A, B]
    assert [b["handle"] for b in store.list_bans()] == [B]
    # an empty board still never reports a lower id than clients may hold
    assert store.clear_all()["through"] == 3
    assert store.create_post(author=A, text="fresh")["id"] == 4


def test_clear_all_removes_only_unreferenced_blobs(store, tmp_path):
    blobs = tmp_path / "blobs"
    shared = store.add_attachment(A, "s.txt", b"shared")
    gone = store.add_attachment(A, "g.txt", b"gone")
    store.create_post(author=A, text="x", attachments=[shared["id"], gone["id"]])
    pending = store.add_attachment(B, "p.txt", b"pending")
    store.clear_all()
    assert not (blobs / shared["sha256"]).exists() and not (blobs / gone["sha256"]).exists()
    assert not (blobs / pending["sha256"]).exists()
    fails("UNKNOWN_ATTACHMENT", lambda: store.get_attachment(pending["id"]), 404)
    kept = store.add_attachment(A, "k.txt", b"kept")
    store.create_post(author=A, text="keep", attachments=[kept["id"]])
    dup = store.add_attachment(B, "d.txt", b"kept")
    store.create_post(author=B, text="dup", attachments=[dup["id"]])
    store.purge_author(B)  # B's row goes, A's row still references the same digest
    assert (blobs / kept["sha256"]).read_bytes() == b"kept"
    assert store.get_attachment(kept["id"])[1].read_bytes() == b"kept"


def test_clear_all_logs_blob_unlink_failure(store, tmp_path, monkeypatch, caplog):
    att = store.add_attachment(A, "a.txt", b"locked")
    from pathlib import Path

    def refuse(self, missing_ok=False):
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "unlink", refuse)
    assert store.clear_all()["through"] == 0
    assert att["sha256"] in caplog.text
    fails("UNKNOWN_ATTACHMENT", lambda: store.get_attachment(att["id"]), 404)


def test_purge_author_removes_only_their_posts_and_uploads(store, tmp_path):
    a_att = store.add_attachment(A, "a.txt", b"from a")
    store.create_post(author=A, text=f"a1 @{B}", attachments=[a_att["id"]])
    b_post = store.create_post(author=B, text=f"b1 @{A}")
    store.create_post(author=A, text="a2")
    a_pending = store.add_attachment(A, "p.txt", b"a pending")
    b_pending = store.add_attachment(B, "q.txt", b"b pending")
    purge = store.purge_author(A)
    assert purge["scope"] == "author" and purge["author"] == A and purge["through"] == 3
    assert [p["id"] for p in store.list_posts()] == [b_post["id"]]
    assert store.list_posts(mention=B) == []
    assert [p["id"] for p in store.list_posts(mention=A)] == [b_post["id"]]
    for att in (a_att, a_pending):
        fails("UNKNOWN_ATTACHMENT", lambda: store.get_attachment(att["id"]), 404)
        assert not (tmp_path / "blobs" / att["sha256"]).exists()
    assert store.get_attachment(b_pending["id"])[1].read_bytes() == b"b pending"
    fails("UNKNOWN_AUTHOR", lambda: store.purge_author("ghost_00000000"), 404)
    assert store.list_members()[0]["handle"] == A  # membership is kept


def test_ban_with_purge(store):
    store.create_post(author=A, text="a")
    store.create_post(author=B, text="b")
    ban = store.ban(A, purge=True)
    assert ban["purge"]["scope"] == "author" and ban["purge"]["author"] == A
    assert [p["author"] for p in store.list_posts()] == [B]
    assert store.list_purges() == [ban["purge"]]


def test_purges_are_recorded_in_order(store, monkeypatch):
    monkeypatch.setattr("services.message_board.store._now", lambda: "2026-10-13T00:00:00Z")
    store.create_post(author=A, text="a")
    first = store.purge_author(A)
    second = store.clear_all()
    assert first == {"id": 1, "scope": "author", "author": A, "through": 1,
                     "created_at": "2026-10-13T00:00:00Z"}
    assert second == {"id": 2, "scope": "all", "through": 1,
                      "created_at": "2026-10-13T00:00:00Z"}
    assert store.list_purges() == [first, second]
    assert store.list_purges(after=1) == [second]
    assert store.list_purges(after=2) == []
    fails("INVALID", lambda: store.list_purges(after=-1), 422)


def test_members_report_banned_flag(store):
    assert {m["handle"]: m["banned"] for m in store.list_members()} == {A: False, B: False}
    store.ban(B)
    assert {m["handle"]: m["banned"] for m in store.list_members()} == {A: False, B: True}
    assert store.register_member("new_00000000", "user", key=OTHER_KEY)[0]["banned"] is False
