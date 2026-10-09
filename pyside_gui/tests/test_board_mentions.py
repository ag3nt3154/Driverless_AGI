"""Board composer @ autocomplete and @mention delivery into agent loops."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import Qt

from pyside_gui.agents_controller import MAX_AGENT_WAKES, AgentsController, mention_message
from pyside_gui.sidebars.board_composer import MentionEdit, mention_prefix
from pyside_gui.tests.session_stub import StubSession

HELPER = "helper_abcdef12"


def test_mention_prefix_only_at_a_word_start():
    assert mention_prefix("hi @he") == "@he"
    assert mention_prefix("@") == "@"
    assert mention_prefix("(@main_1") == "@main_1"
    assert mention_prefix("mail@he") is None
    assert mention_prefix("hi @he there") is None


def test_autocomplete_inserts_the_selected_handle(qtbot):
    edit = MentionEdit()
    qtbot.addWidget(edit)
    edit.show()
    edit.set_mentions([HELPER, "main_11112222"])
    qtbot.keyClicks(edit, "ping @he")
    assert edit.completer.visible_count() == 1
    assert edit.completer.selected_command() == f"@{HELPER}"
    qtbot.keyClick(edit, Qt.Key.Key_Tab)
    assert edit.text() == f"ping @{HELPER} "
    assert edit.completer.isHidden()


def test_enter_submits_and_shift_enter_breaks_the_line(qtbot):
    edit = MentionEdit()
    qtbot.addWidget(edit)
    sent = []
    edit.submitted.connect(lambda: sent.append(edit.text()))
    qtbot.keyClicks(edit, "one")
    qtbot.keyClick(edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    qtbot.keyClicks(edit, "two")
    qtbot.keyClick(edit, Qt.Key.Key_Return)
    assert sent == ["one\ntwo"]


def _post(post_id, author, mentions, text="hey"):
    return {"id": post_id, "author": author, "text": text, "mentions": mentions, "meme": None,
            "reply_to": None, "attachments": [], "created_at": "2026-10-09T12:00:00Z"}


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
    controller.on_board_mention(_post(5, "user_aaaabbbb", [HELPER]), "user_aaaabbbb")
    helper.deliver_mention.assert_called_once()
    main.deliver_mention.assert_not_called()
    text = helper.deliver_mention.call_args.args[0]
    assert "You were mentioned" in text and "user_aaaabbbb" in text and "hey" in text
    controller.on_board_mention(_post(6, HELPER, [HELPER]), "user_aaaabbbb")
    assert helper.deliver_mention.call_count == 1


def test_agent_to_agent_wakes_stop_at_the_cap_until_the_user_speaks():
    helper = _agent(HELPER)
    controller = _agents_window([helper])
    for post_id in range(MAX_AGENT_WAKES + 2):
        controller.on_board_mention(_post(post_id + 1, "main_11112222", [HELPER]), "user_x")
    assert helper.deliver_mention.call_count == MAX_AGENT_WAKES
    helper._conversation.append_info.assert_called()
    controller.on_board_mention(_post(99, "user_x", [HELPER]), "user_x")
    assert helper.deliver_mention.call_count == MAX_AGENT_WAKES + 1 and helper.agent_wakes == 0


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


def test_controller_wakes_only_for_live_posts_and_feeds_autocomplete(qtbot):
    from pyside_gui.board_controller import BoardController
    from pyside_gui.tests.test_board_controller import _window

    window = _window(qtbot)
    calls = []
    window._on_board_mention = lambda post, user: calls.append((post["id"], user))
    controller = BoardController(window)
    controller.runtime = SimpleNamespace(session=SimpleNamespace(handle="main_11112222"),
                                         user_handle="user_aaaabbbb")
    controller.sessions = [SimpleNamespace(handle="main_11112222")]
    controller._on_post(_post(3, "main_11112222", [HELPER]))  # before the snapshot settles
    controller._live_after = 3
    controller._on_post(_post(2, HELPER, ["main_11112222"]))  # snapshot-era post
    controller._on_post(_post(4, "user_aaaabbbb", [HELPER]))
    assert calls == [(4, "user_aaaabbbb")]
    controller._on_members(["coder_12345678", "user_aaaabbbb"])
    items = window._left_sidebar.board_view._input.completer._all_items
    handles = {name for name, _ in items}
    assert {f"@{HELPER}", "@main_11112222", "@coder_12345678"} <= handles
    assert "@user_aaaabbbb" not in handles
