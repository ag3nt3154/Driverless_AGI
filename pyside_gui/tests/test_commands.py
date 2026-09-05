from __future__ import annotations

from unittest.mock import MagicMock

from pyside_gui.commands import SlashCommandHandler, UIWidgets


def _make_widgets():
    return UIWidgets(
        conversation=MagicMock(),
        right_sidebar=MagicMock(),
        left_sidebar=MagicMock(),
    )


def test_unknown_command_shows_error():
    w = _make_widgets()
    handler = SlashCommandHandler(w, MagicMock(), MagicMock())
    result = handler.handle("/nope")
    assert result is None
    w.conversation.append_error.assert_called_once()


def test_exit_returns_exit_sentinel():
    w = _make_widgets()
    handler = SlashCommandHandler(w, MagicMock(), MagicMock())
    result = handler.handle("/exit")
    assert result == "__EXIT__"


def test_clear_resets_conversation():
    w = _make_widgets()
    handler = SlashCommandHandler(w, MagicMock(), MagicMock())
    handler._worker_alive = lambda: False
    result = handler.handle("/clear")
    assert result is None
    w.conversation.clear.assert_called_once()


def test_clear_routes_plan_clear_to_left_sidebar():
    """The plan panel moved to the left sidebar; /clear must clear it there."""
    w = _make_widgets()
    # A bare MagicMock would auto-vivify and silently absorb a stray
    # right_sidebar.update_plan call, making assert_not_called vacuous.
    # Make any such call fail loudly instead.
    w.right_sidebar.update_plan.side_effect = AssertionError(
        "right_sidebar.update_plan must not be called — the plan panel "
        "lives in the left sidebar"
    )
    handler = SlashCommandHandler(w, MagicMock(), MagicMock())
    handler._worker_alive = lambda: False
    handler.handle("/clear")
    w.left_sidebar.update_plan.assert_called_once_with([], "")
    w.right_sidebar.update_plan.assert_not_called()


def test_help_shows_info():
    w = _make_widgets()
    handler = SlashCommandHandler(w, MagicMock(), MagicMock())
    handler.handle("/help")
    w.conversation.append_info.assert_called()
