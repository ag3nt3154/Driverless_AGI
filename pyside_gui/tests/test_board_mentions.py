"""Board @mention delivery into agent loops."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from pyside_gui.agents_controller import AgentsController, mention_message
from pyside_gui.tests.session_stub import StubSession

HELPER = "helper_abcdef12"


def _post(post_id, author, mentions, text="hey", author_kind="agent"):
    return {"id": post_id, "author": author, "text": text, "mentions": mentions, "meme": None,
            "author_kind": author_kind, "reply_to": None, "attachments": [],
            "created_at": "2026-10-09T12:00:00Z"}


def _agents_window(sessions):
    controller = AgentsController.__new__(AgentsController)
    controller.window = SimpleNamespace(_sessions=sessions)
    controller.refresh = lambda *_args: None
    return controller


def _agent(handle):
    session = StubSession(active=False, handle=handle)
    session._board_session = SimpleNamespace(handle=handle)
    session.deliver_mention = MagicMock()
    return session


def test_mention_reaches_only_the_named_agent_and_never_its_author():
    main, helper = _agent("main_11112222"), _agent(HELPER)
    controller = _agents_window([main, helper])
    controller.on_board_mention(_post(5, "user_aaaabbbb", [HELPER], author_kind="user"))
    helper.deliver_mention.assert_called_once()
    main.deliver_mention.assert_not_called()
    text = helper.deliver_mention.call_args.args[0]
    assert "You were mentioned" in text and "user_aaaabbbb" in text and "hey" in text
    controller.on_board_mention(_post(6, HELPER, [HELPER]))
    assert helper.deliver_mention.call_count == 1


def test_agent_mentions_always_wake():
    """Agent-to-agent mentions are never capped."""
    helper = _agent(HELPER)
    controller = _agents_window([helper])
    for post_id in range(20):
        controller.on_board_mention(_post(post_id + 1, "main_11112222", [HELPER]))
    assert helper.deliver_mention.call_count == 20


def test_deliver_mention_starts_a_turn_when_idle_and_steers_when_busy(monkeypatch):
    from pyside_gui import agent_session

    session = StubSession()
    session._dispatch_agent = MagicMock()
    session._notify = MagicMock()
    session.deliver_mention("[Message board] You were mentioned in this post:\n#5 x: hi")
    assert session._dispatch_agent.call_args.args[0].text.startswith("[Message board]")
    queued = []
    monkeypatch.setattr(agent_session.SteerQueue, "for_window",
                        classmethod(lambda cls, win: SimpleNamespace(submit=queued.append)))
    session._worker = SimpleNamespace(is_alive=lambda: True)
    session.deliver_mention("[Message board] again\n#6 x: hi")
    assert [s.text for s in queued] == ["[Message board] again\n#6 x: hi"]
    assert session._dispatch_agent.call_count == 1


def test_mention_message_uses_read_board_format():
    text = mention_message(_post(7, "user_aaaabbbb", [HELPER], text=f"@{HELPER} look"), HELPER)
    assert "#7" in text and f"@{HELPER} look" in text


def test_peer_woken_by_its_spawner_is_told_the_handoff_is_posted_for_it():
    """Observed 2026-10-17: a peer posted its result by hand and then write_handoff posted it again."""
    main, peer = _agent("main_11112222"), _agent("probe_0d68a910")
    peer.spawned_by = "main_11112222"
    controller = _agents_window([main, peer])
    controller.on_board_mention(_post(1, "main_11112222", ["probe_0d68a910"],
                                      text="@probe_0d68a910 [task] add 2+2"))
    text = peer.deliver_mention.call_args.args[0]
    assert "#1" in text and "[task] add 2+2" in text
    assert "write_handoff" in text and "posted to @main_11112222 automatically" in text
    assert "Do not post your result, progress or acknowledgements" in text
    assert "Reply on the board" not in text


def test_spawner_woken_by_its_peer_is_told_not_to_mention_it_back():
    """Observed 2026-10-17: main thanked @probe, which woke probe for a second [done]."""
    main, peer = _agent("main_11112222"), _agent("probe_0d68a910")
    peer.spawned_by = "main_11112222"
    controller = _agents_window([main, peer])
    controller.on_board_mention(_post(4, "probe_0d68a910", ["main_11112222"],
                                      text="@main_11112222 [done] 2+2=4"))
    text = main.deliver_mention.call_args.args[0]
    assert "automatic report of your peer @probe_0d68a910" in text
    assert "unless you give it new work" in text and "Reply on the board" not in text


def test_unrelated_agents_keep_the_plain_mention_message():
    main, helper = _agent("main_11112222"), _agent(HELPER)
    controller = _agents_window([main, helper])  # helper is user-spawned: spawned_by None
    controller.on_board_mention(_post(2, "main_11112222", [HELPER]))
    controller.on_board_mention(_post(3, HELPER, ["main_11112222"]))
    expected = mention_message(_post(2, "main_11112222", [HELPER]), HELPER)
    assert helper.deliver_mention.call_args.args[0] == expected
    assert "Reply on the board" in main.deliver_mention.call_args.args[0]


def test_controller_wakes_only_for_live_posts(qtbot):
    from pyside_gui.board_controller import BoardController
    from pyside_gui.tests.test_board_controller import _window

    window = _window(qtbot)
    calls = []
    window._on_board_mention = lambda post: calls.append(post["id"])
    controller = BoardController(window)
    controller.runtime = SimpleNamespace(session=SimpleNamespace(handle="main_11112222"),
                                         temp=None)
    controller.sessions = [SimpleNamespace(handle="main_11112222")]
    controller._on_post(_post(3, "main_11112222", [HELPER]))  # before the snapshot settles
    controller._live_after = 3
    controller._on_post(_post(2, HELPER, ["main_11112222"]))  # snapshot-era post
    controller._on_post(_post(4, "user_aaaabbbb", [HELPER], author_kind="user"))
    assert calls == [4]


def test_only_the_exact_handle_wakes_a_spawned_agent():
    """Reported bug: main posted to its worker by name and the worker never woke."""
    from services.message_board.store import extract_mentions

    main, worker = _agent("main_11112222"), _agent("worker_1a2b3c4d")
    controller = _agents_window([main, worker])
    for text in ("@worker hi", "@worker-1a2b3c4d hi", "@Worker_1a2b3c4d hi"):
        controller.on_board_mention(_post(1, "main_11112222", extract_mentions(text), text))
    worker.deliver_mention.assert_not_called()
    controller.on_board_mention(
        _post(2, "main_11112222", extract_mentions("@worker_1a2b3c4d hi"), "@worker_1a2b3c4d hi"))
    worker.deliver_mention.assert_called_once()
