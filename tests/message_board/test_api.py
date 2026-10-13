"""HTTP and streaming contract of the board service."""
import asyncio
import json
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from agent.board_client import BoardClient
from services.message_board.app import PostHub, create_app, post_events
from services.message_board.lifecycle import ShutdownControl
from services.message_board.store import BoardStore

A = "main_3f9a1c2e"
KEY = "k" * 43
KEYED = {"X-Dagi-Member-Key": KEY}


@pytest.fixture
def board(tmp_path):
    store = BoardStore(tmp_path / "board.sqlite3")
    yield store
    store.close()


def test_api_roundtrip(board):
    with TestClient(create_app(board)) as client:
        member = client.post("/members", json={"handle": A, "kind": "agent", "key": KEY})
        assert member.status_code == 201
        again = client.post("/members", json={"handle": A, "kind": "agent", "key": KEY})
        assert again.status_code == 200
        assert client.get("/members").json() == [again.json()]
        upload = client.post("/attachments", data={"uploader": A}, headers=KEYED,
                             files={"file": ("hello.txt", b"hello", "text/plain")})
        assert upload.status_code == 201, upload.text
        attachment = upload.json()
        response = client.get(f"/attachments/{attachment['id']}")
        assert response.content == b"hello"
        assert response.headers["content-type"].startswith("text/plain")
        assert 'filename="hello.txt"' in response.headers["content-disposition"]
        assert client.get(f"/attachments/{attachment['id']}/meta").json() == attachment
        post = client.post("/posts", headers=KEYED, json={"author": A, "text": f"hi @{A}",
                                                          "attachments": [attachment["id"]]})
        assert post.status_code == 201
        assert client.get("/posts", params={"after": 0, "mention": A}).json() == [post.json()]
        assert client.get("/posts", params={"after": 1}).json() == []
        assert client.get("/attachments/unknown").json()["code"] == "UNKNOWN_ATTACHMENT"


def test_auth_and_errors(board):
    with TestClient(create_app(board, "secret")) as client:
        for path in ("/", "/health"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["x-content-type-options"] == "nosniff"
        health = client.get("/health").json()
        assert health["version"] == 1 and health["pid"] > 0 and health["instance_id"]
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            response = client.get("/posts", headers=headers)
            assert response.status_code == 401
            assert response.json()["code"] == "UNAUTHORIZED"
            assert response.headers["x-content-type-options"] == "nosniff"
        headers = {"Authorization": "Bearer secret"}
        for path in ("/posts?limit=0", "/posts?after=-1"):
            response = client.get(path, headers=headers)
            assert response.status_code == 422 and set(response.json()) == {"error", "code"}
        assert client.post("/posts", json={}, headers=headers).json()["code"] == "INVALID"


def test_sse_backlog_notify_ping_and_race(board, monkeypatch):
    monkeypatch.setattr("services.message_board.app.PING_SECONDS", 0.01)
    board.register_member(A, "agent", key=KEY)
    first = board.create_post(author=A, text="first")

    async def run():
        hub = PostHub()
        events = post_events(board, hub, 0)
        assert await anext(events) == f"id: 1\nevent: post\ndata: {json.dumps(first)}\n\n"
        waiting = asyncio.create_task(anext(events))
        await asyncio.sleep(0)
        second = board.create_post(author=A, text="second")
        await hub.notify()
        assert await waiting == f"id: 2\nevent: post\ndata: {json.dumps(second)}\n\n"
        assert await anext(events) == ": ping\n\n"
        seen = hub.version
        await hub.notify()
        assert await hub.wait_past(seen, 0.01)
        await events.aclose()
        latest = post_events(board, hub, None)
        assert await anext(latest) == ": ping\n\n"
        await latest.aclose()
    asyncio.run(run())


def test_posts_and_stream_include_author_kind(board):
    user = "web_12345678"
    with TestClient(create_app(board)) as client:
        assert client.post("/members", json={"handle": A, "kind": "agent", "key": KEY}).status_code == 201
        assert client.post("/members", json={"handle": user, "kind": "user",
                                             "host": "web", "key": KEY}).status_code == 201
        agent_post_response = client.post("/posts", headers=KEYED,
                                          json={"author": A, "text": "agent"})
        user_post_response = client.post("/posts", headers=KEYED,
                                         json={"author": user, "text": "user"})
        assert agent_post_response.status_code == 201
        assert user_post_response.status_code == 201
        agent_post = agent_post_response.json()
        user_post = user_post_response.json()
        assert agent_post["author_kind"] == "agent"
        assert user_post["author_kind"] == "user"

        posts = client.get("/posts", params={"after": 0}).json()
        assert [post["author_kind"] for post in posts] == ["agent", "user"]

    async def backlog():
        events = post_events(board, PostHub(), 0)
        try:
            received = [json.loads((await anext(events)).split("data: ", 1)[1])
                        for _ in range(2)]
            assert [post["author_kind"] for post in received] == ["agent", "user"]
            assert [post["id"] for post in received] == [agent_post["id"], user_post["id"]]
        finally:
            await events.aclose()

    asyncio.run(backlog())


ADMIN = {"X-Dagi-Admin-Key": "z" * 43}


def admin_app(board):
    control = ShutdownControl("a" * 32, "b" * 64, lambda: None, admin_key=ADMIN["X-Dagi-Admin-Key"])
    return create_app(board, shutdown=control)


def test_admin_clear_and_ban_routes(board):
    B = "web_12345678"
    with TestClient(admin_app(board), client=("127.0.0.1", 123)) as client:
        for handle, kind in ((A, "agent"), (B, "user")):
            assert client.post("/members", json={"handle": handle, "kind": kind,
                                                 "key": handle + KEY}).status_code == 201
        def post(handle, text):
            return client.post("/posts", headers={"X-Dagi-Member-Key": handle + KEY},
                               json={"author": handle, "text": text})
        first = post(A, "one").json()
        post(B, "two")
        hub = client.app.state.hub
        version = hub.version
        clear = client.post("/admin/clear", headers=ADMIN)
        assert clear.status_code == 200
        purge = clear.json()
        assert purge["scope"] == "all" and purge["through"] == first["id"] + 1
        assert hub.version == version + 1
        assert client.get("/posts", params={"after": 0}).json() == []

        post(A, "three")
        kept = post(B, "four").json()
        assert client.get("/admin/bans", headers=ADMIN).json() == []
        version = hub.version
        ban = client.post("/admin/bans", headers=ADMIN, json={"handle": A, "purge": True})
        assert ban.status_code == 201, ban.text
        body = ban.json()
        assert body["handle"] == A and body["purge"]["scope"] == "author"
        assert body["purge"]["author"] == A
        assert hub.version == version + 1
        assert client.get("/posts", params={"after": 0}).json() == [kept]
        refused = post(A, "again")
        assert refused.status_code == 403 and refused.json()["code"] == "BANNED"
        assert [b["handle"] for b in client.get("/admin/bans", headers=ADMIN).json()] == [A]
        assert client.post("/admin/bans", headers=ADMIN,
                           json={"handle": A, "extra": 1}).status_code == 422
        unknown = client.post("/admin/bans", headers=ADMIN, json={"handle": "nobody"})
        assert unknown.status_code == 404 and unknown.json()["code"] == "UNKNOWN_AUTHOR"
        assert client.post("/admin/bans", headers=ADMIN,
                           json={"handle": A, "purge": "yes"}).status_code == 422
        plain = client.post("/admin/bans", headers=ADMIN, json={"handle": B})
        assert plain.status_code == 201 and plain.json()["purge"] is None

        response = client.delete(f"/admin/bans/{A}", headers=ADMIN)
        assert response.status_code == 204 and response.content == b""
        again = client.delete(f"/admin/bans/{A}", headers=ADMIN)
        assert again.status_code == 404 and again.json()["code"] == "UNKNOWN_BAN"
        assert post(A, "back").status_code == 201
        assert [b["handle"] for b in client.get("/admin/bans", headers=ADMIN).json()] == [B]


def test_stream_replays_purges_before_posts(board):
    board.register_member(A, "agent", key=KEY)
    board.create_post(author=A, text="gone")
    purge = board.clear_all()
    kept = board.create_post(author=A, text="kept")

    async def run():
        for after in (0, None):
            events = post_events(board, PostHub(), after)
            try:
                assert await anext(events) == f"event: purge\ndata: {json.dumps(purge)}\n\n"
                if after == 0:
                    assert await anext(events) == (
                        f"id: {kept['id']}\nevent: post\ndata: {json.dumps(kept)}\n\n")
            finally:
                await events.aclose()
    asyncio.run(run())


def test_stream_pushes_live_purge(board, monkeypatch):
    monkeypatch.setattr("services.message_board.app.PING_SECONDS", 5)
    board.register_member(A, "agent", key=KEY)
    first = board.create_post(author=A, text="first")

    async def run():
        hub = PostHub()
        events = post_events(board, hub, 0)
        try:
            assert (await anext(events)).startswith("id: 1\nevent: post")
            waiting = asyncio.create_task(anext(events))
            await asyncio.sleep(0)
            purge = board.purge_author(A)
            await hub.notify()
            assert await asyncio.wait_for(waiting, 2) == (
                f"event: purge\ndata: {json.dumps(purge)}\n\n")
            assert purge["through"] >= first["id"]
            # A purge-only change must not leave the stream waiting before new posts.
            second = board.create_post(author=A, text="second")
            await hub.notify()
            assert await asyncio.wait_for(anext(events), 2) == (
                f"id: {second['id']}\nevent: post\ndata: {json.dumps(second)}\n\n")
        finally:
            await events.aclose()
    asyncio.run(run())


def test_user_member_attachment_is_fetchable_by_agent(board, tmp_path):
    user = "web_12345678"
    app = create_app(board)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    host, port = listener.getsockname()
    base_url = f"http://{host}:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="critical"))
    server_errors = []

    def run_server():
        try:
            server.run(sockets=[listener])
        except BaseException as error:
            server_errors.append(error)

    thread = threading.Thread(target=run_server, name="message-board-test-server", daemon=True)
    thread.start()
    user_client = BoardClient(base_url)
    agent_client = BoardClient(base_url)
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, f"uvicorn did not start: {server_errors!r}"

        user_client.register(user, "user", host="web", key=KEY)
        agent_client.register(A, "agent", key="a" * 43)
        uploaded_bytes = b"from the web"
        source = tmp_path / "note.txt"
        source.write_bytes(uploaded_bytes)
        attachment = user_client.upload(user, source, key=KEY)
        user_client.post(user, "from web", key=KEY, attachments=[attachment["id"]])

        meta, path = agent_client.fetch_attachment(attachment["id"],
                                                   project_root=tmp_path / "agent")
        assert meta == attachment
        assert path.read_bytes() == uploaded_bytes
    finally:
        user_client.close()
        agent_client.close()
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
    assert not thread.is_alive(), "uvicorn test server did not stop"


def test_store_errors_and_latest_reads(board):
    with TestClient(create_app(board)) as client:
        assert client.post("/posts", headers=KEYED,
                           json={"author": A, "text": "x"}).status_code == 404
        client.post("/members", json={"handle": A, "kind": "agent", "key": KEY})
        conflict = client.post("/members", json={"handle": A, "kind": "user", "key": KEY})
        assert conflict.status_code == 409 and conflict.json()["code"] == "HANDLE_TAKEN"
        for i in range(3):
            client.post("/posts", headers=KEYED, json={"author": A, "text": str(i)})
        assert [p["id"] for p in client.get("/posts?limit=2").json()] == [2, 3]
        assert client.get("/posts?after=9223372036854775808").status_code == 422
        assert client.post("/posts", headers=KEYED,
                           json={"author": A, "text": "x" * 701}).status_code == 422
        assert client.get("/missing").json()["code"] == "INVALID"


def test_writes_as_another_member_are_refused(board, tmp_path):
    """Holding the board token is not enough to post or upload under someone else's handle."""
    with TestClient(create_app(board, "secret")) as client:
        token = {"Authorization": "Bearer secret"}
        assert client.post("/members", headers=token,
                           json={"handle": A, "kind": "agent", "key": KEY}).status_code == 201
        hijack = client.post("/members", headers=token,
                             json={"handle": A, "kind": "agent", "key": "x" * 43})
        assert hijack.status_code == 409 and hijack.json()["code"] == "HANDLE_TAKEN"
        assert client.post("/members", headers=token,
                           json={"handle": "eve_00000000", "kind": "agent"}).status_code == 422
        for key in (None, "x" * 43):
            headers = token if key is None else {**token, "X-Dagi-Member-Key": key}
            post = client.post("/posts", headers=headers, json={"author": A, "text": "forged"})
            assert post.status_code == 403 and post.json()["code"] == "FORBIDDEN"
            upload = client.post("/attachments", headers=headers, data={"uploader": A},
                                 files={"file": ("a.txt", b"forged")})
            assert upload.status_code == 403
        assert client.get("/posts", headers=token).json() == []
        assert not (tmp_path / "blobs").exists()
        assert client.post("/posts", headers={**token, **KEYED},
                           json={"author": A, "text": "real"}).status_code == 201


def test_unexpected_store_failure_is_safe_json(board, monkeypatch, caplog):
    def fail():
        raise OSError("private path and secret must stay in service logs")
    monkeypatch.setattr(board, "list_members", fail)
    with TestClient(create_app(board), raise_server_exceptions=False) as client:
        result = client.get("/members")
    assert result.status_code == 500 and result.json()["code"] == "INTERNAL_ERROR"
    assert "private path" not in result.text and "secret" not in result.text
    assert result.headers["x-content-type-options"] == "nosniff"
    assert "message board request failed" in caplog.text
