"""Worker-thread spawn flow: register-before-post task delivery (Subtask 6, D2/D13)."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent.board_client import BoardClient, BoardError, BoardSession
from pyside_gui import agent_session
from pyside_gui.peers import task_post
from pyside_gui.tests.session_stub import StubSession, stub_window


def _fake_peer(handle="fixer_1234abcd", board_calls=None):
    board_calls = board_calls if board_calls is not None else []
    peer_client = SimpleNamespace(
        register=lambda *a, **k: board_calls.append(("register", a, k)),
    )
    peer_board = SimpleNamespace(client=peer_client, key="peer-key", handle=handle)
    peer = StubSession(handle=handle)
    peer._board_session = peer_board
    return peer, board_calls


class FakeMainBoard:
    def __init__(self, handle="main_11112222", calls=None, posts=None, fail=False):
        self.handle = handle
        self.calls = calls if calls is not None else []
        self._posts = posts if posts is not None else []
        self.fail = fail

    def post(self, text, files=()):
        self.calls.append(("post", text, tuple(files)))
        if self.fail:
            raise BoardError("FAIL", "boom")
        post = {"id": len(self._posts) + 1, "text": text}
        self._posts.append(post)
        return post


def _run_and_wait(qtbot, main, slug, task, close_on_done):
    result = {}

    def _run():
        result["text"] = main._spawn_from_worker(slug, task, close_on_done)

    thread = threading.Thread(target=_run)
    thread.start()
    qtbot.waitUntil(lambda: "text" in result, timeout=5000)
    thread.join(timeout=5)
    return result["text"]


def test_only_main_session_gets_spawn_callback():
    main = StubSession(handle="main_12345678")
    other = StubSession(handle="helper_abcdefab")
    window = stub_window(_main=main)
    main.win = window
    other.win = window

    assert main._spawn_agent == main._spawn_from_worker
    assert other._spawn_agent is None

    from pyside_gui.bridge import AgentBridge

    bridge = AgentBridge()
    callbacks = bridge.build_callbacks(spawn_agent=main._spawn_agent)
    assert callbacks.spawn_agent == main._spawn_agent
    default_callbacks = bridge.build_callbacks()
    assert default_callbacks.spawn_agent is None


def test_spawn_registers_before_posting_task(qtbot):
    calls = []
    peer, board_calls = _fake_peer(board_calls=calls)
    main = StubSession(handle="main_12345678")
    main.win = stub_window(_main=main, _agents=SimpleNamespace(spawn_peer=lambda *a, **k: peer))
    main._board_session = FakeMainBoard(calls=calls)

    text = _run_and_wait(qtbot, main, "fixer", "do it", True)

    assert [c[0] for c in calls] == ["register", "post"]
    expected_text, _attach = task_post(peer.handle, "do it")
    assert calls[1][1] == expected_text
    assert text.startswith("Spawned ")
    assert "@mention the peer only to give it new work" in text


def test_long_task_is_attached_as_task_md(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(agent_session, "DAGI_ROOT", tmp_path)
    calls = []
    peer, board_calls = _fake_peer(board_calls=calls)
    main = StubSession(handle="main_12345678")
    main.win = stub_window(_main=main, _agents=SimpleNamespace(spawn_peer=lambda *a, **k: peer))
    main._board_session = FakeMainBoard(calls=calls)
    task = "x" * 2000

    _run_and_wait(qtbot, main, "fixer", task, False)

    post_calls = [c for c in calls if c[0] == "post"]
    assert len(post_calls) == 1
    files = post_calls[0][2]
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == task


def test_task_mention_is_recorded_on_real_board(qtbot, tmp_path, monkeypatch):
    from services.message_board.app import create_app
    from services.message_board.store import BoardStore

    monkeypatch.setattr(agent_session, "DAGI_ROOT", tmp_path)
    store = BoardStore(tmp_path / "server" / "b.sqlite3")
    app = create_app(store)
    with TestClient(app) as http:
        client = BoardClient("http://board", http=http)
        client.register("main_11112222", "agent", key="k" * 43)
        main_board = BoardSession(client, "main_11112222", "k" * 43)

        peer_client = BoardClient("http://board", http=http)
        peer_board = BoardSession(peer_client, "fixer_1234abcd", "p" * 43)

        peer = StubSession(handle="fixer_1234abcd")
        peer._board_session = peer_board
        main = StubSession(handle="main_12345678")
        main.win = stub_window(_main=main, _agents=SimpleNamespace(spawn_peer=lambda *a, **k: peer))
        main._board_session = main_board

        _run_and_wait(qtbot, main, "fixer", "please fix it", False)

        posts = client.posts(mention="fixer_1234abcd")
        assert len(posts) == 1
        assert "please fix it" in posts[0]["text"]
    store.close()


def test_spawn_error_returns_text_and_posts_nothing(qtbot):
    calls = []
    main = StubSession(handle="main_12345678")
    main.win = stub_window(
        _main=main, _agents=SimpleNamespace(spawn_peer=lambda *a, **k: "Error: at the limit"))
    main._board_session = FakeMainBoard(calls=calls)

    text = _run_and_wait(qtbot, main, "fixer", "do it", False)

    assert text == "Error: at the limit"
    assert calls == []


def test_spawn_timeout_returns_error(monkeypatch):
    monkeypatch.setattr(agent_session, "SPAWN_TIMEOUT_S", 0.1)
    main = StubSession(handle="main_12345678")
    main.win = stub_window(_main=main)
    main._board_session = FakeMainBoard()
    # Patch _spawn_on_main to do nothing, so the future never resolves.
    monkeypatch.setattr(agent_session.AgentSession, "_spawn_on_main", lambda self, payload: None)

    result = main._spawn_from_worker("fixer", "do it", False)

    assert "did not answer the spawn request" in result


def test_late_spawn_after_timeout_creates_no_peer(qtbot, monkeypatch):
    """GUI thread busy past the timeout: the queued call runs later and must do nothing."""
    monkeypatch.setattr(agent_session, "SPAWN_TIMEOUT_S", 0.1)
    calls = []
    main = StubSession(handle="main_12345678")
    main.win = stub_window(_main=main, _agents=SimpleNamespace(
        spawn_peer=lambda *a, **k: calls.append(a) or "Error: unused"))
    main._board_session = FakeMainBoard()

    # Called on the GUI thread itself, so the queued slot cannot run during the wait.
    result = main._spawn_from_worker("fixer", "do it", False)
    qtbot.wait(50)  # now the event loop delivers the late call

    assert "did not answer the spawn request" in result
    assert calls == []


def test_spawn_on_main_sets_exception_never_hangs(qtbot):
    def _raise(*a, **k):
        raise RuntimeError("boom")

    main = StubSession(handle="main_12345678")
    main.win = stub_window(_main=main, _agents=SimpleNamespace(spawn_peer=_raise))
    main._board_session = FakeMainBoard()

    text = _run_and_wait(qtbot, main, "fixer", "do it", False)

    assert text.startswith("Error: could not spawn")
