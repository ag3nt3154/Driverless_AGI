"""HTTP and streaming contract of the board service."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from services.message_board.app import PostHub, create_app, post_events
from services.message_board.store import BoardStore

A = "main_3f9a1c2e"


@pytest.fixture
def board(tmp_path):
    store = BoardStore(tmp_path / "board.sqlite3")
    yield store
    store.close()


def test_api_roundtrip(board):
    with TestClient(create_app(board)) as client:
        member = client.post("/members", json={"handle": A, "kind": "agent"})
        assert member.status_code == 201
        again = client.post("/members", json={"handle": A, "kind": "agent"})
        assert again.status_code == 200
        assert client.get("/members").json() == [again.json()]
        upload = client.post("/attachments", data={"uploader": A},
                             files={"file": ("hello.txt", b"hello", "text/plain")})
        assert upload.status_code == 201, upload.text
        attachment = upload.json()
        response = client.get(f"/attachments/{attachment['id']}")
        assert response.content == b"hello"
        assert response.headers["content-type"].startswith("text/plain")
        assert 'filename="hello.txt"' in response.headers["content-disposition"]
        assert client.get(f"/attachments/{attachment['id']}/meta").json() == attachment
        post = client.post("/posts", json={"author": A, "text": f"hi @{A}",
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
    board.register_member(A, "agent")
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


def test_store_errors_and_latest_reads(board):
    with TestClient(create_app(board)) as client:
        assert client.post("/posts", json={"author": A, "text": "x"}).status_code == 404
        client.post("/members", json={"handle": A, "kind": "agent"})
        conflict = client.post("/members", json={"handle": A, "kind": "user"})
        assert conflict.status_code == 409 and conflict.json()["code"] == "HANDLE_TAKEN"
        for i in range(3):
            client.post("/posts", json={"author": A, "text": str(i)})
        assert [p["id"] for p in client.get("/posts?limit=2").json()] == [2, 3]
        assert client.get("/posts?after=9223372036854775808").status_code == 422
        assert client.post("/posts", json={"author": A, "text": "x" * 701}).status_code == 422
        assert client.get("/missing").json()["code"] == "INVALID"


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
