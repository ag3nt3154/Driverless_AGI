from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent import session_events as ev
from agent.session_log import SessionLog
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


# ── /revise-history ──────────────────────────────────────────────────────────


def _build_log_with_steps(n_turns: int, steps_per_turn: int) -> SessionLog:
    """Build a SessionLog with the given number of turns, each with the given
    number of steps (tool/call, tool/result, assistant/message per step).

    Mirrors tests/test_session_log_revise.py::_build_log_with_steps so the
    fixture behaves identically to the one the core-logic tests rely on.
    """
    log = SessionLog()
    for t in range(1, n_turns + 1):
        log.append(ev.TURN_START, {"turn": t})
        log.append(
            ev.USER_MESSAGE,
            {"turn": t, "step": 0, "role": "user", "content": f"User turn {t}"},
            surface_op="append",
        )
        for s in range(1, steps_per_turn + 1):
            call_id = f"call_{t}_{s}"
            log.append(ev.STEP_START, {"turn": t, "step": s})
            log.append(
                ev.TOOL_CALL,
                {"turn": t, "step": s, "call_id": call_id, "name": f"tool_{s}", "input": {}},
            )
            log.append(
                ev.TOOL_RESULT,
                {"turn": t, "step": s, "call_id": call_id, "content": f"result {s}"},
                surface_op="append",
            )
            log.append(
                ev.ASSISTANT_MESSAGE,
                {"turn": t, "step": s, "message": {"role": "assistant", "content": f"Response t{t}s{s}"}},
                surface_op="append",
            )
            log.append(ev.STEP_END, {"turn": t, "step": s})
        log.append(ev.TURN_END, {"turn": t, "reason": ev.reason_completed()})
    return log


class _FakeTracker:
    def __init__(self, path: Path) -> None:
        self._path = path


class _FakeLoop:
    """Minimal stand-in for AgentLoop exposing only what _cmd_revise_history touches."""

    def __init__(self, log: SessionLog, tracker_path: Path) -> None:
        self.log = log
        self.tracker = _FakeTracker(tracker_path)
        self.sync_calls = 0

    def _sync_messages(self) -> None:
        self.sync_calls += 1


def _make_handler_with_loop(log: SessionLog, tmp_path: Path):
    w = _make_widgets()
    handler = SlashCommandHandler(w, MagicMock(), tmp_path)
    handler._worker_alive = lambda: False
    loop = _FakeLoop(log, tmp_path / "session.jsonl")
    handler.set_active_loop(loop)
    return w, handler, loop


def test_revise_history_with_no_active_loop_shows_info():
    w = _make_widgets()
    handler = SlashCommandHandler(w, MagicMock(), MagicMock())
    handler._worker_alive = lambda: False
    result = handler.handle("/revise-history")
    assert result is None
    assert "Nothing to revise" in w.conversation.append_info.call_args[0][0]


def test_revise_history_blocked_while_worker_alive(tmp_path: Path):
    log = _build_log_with_steps(1, 1)
    w, handler, loop = _make_handler_with_loop(log, tmp_path)
    handler._worker_alive = lambda: True
    events_before = tuple(log.events)

    with patch("PySide6.QtWidgets.QMessageBox.question") as mock_question:
        result = handler.handle("/revise-history")

    assert result is None
    mock_question.assert_not_called()
    assert "Cannot revise" in w.conversation.append_info.call_args[0][0]
    assert log.events == events_before


def test_revise_history_rejects_non_numeric_argument(tmp_path: Path):
    log = _build_log_with_steps(1, 1)
    w, handler, loop = _make_handler_with_loop(log, tmp_path)
    events_before = tuple(log.events)

    result = handler.handle("/revise-history abc")

    assert result is None
    w.conversation.append_error.assert_called_once()
    assert "Invalid argument" in w.conversation.append_error.call_args[0][0]
    assert log.events == events_before


@pytest.mark.parametrize("arg", ["0", "-1"])
def test_revise_history_rejects_non_positive_n(arg, tmp_path: Path):
    log = _build_log_with_steps(1, 1)
    w, handler, loop = _make_handler_with_loop(log, tmp_path)
    events_before = tuple(log.events)

    result = handler.handle(f"/revise-history {arg}")

    assert result is None
    w.conversation.append_error.assert_called_once()
    assert "N must be at least 1" in w.conversation.append_error.call_args[0][0]
    assert log.events == events_before


def test_revise_history_errors_when_too_many_steps_requested(tmp_path: Path):
    # Only 2 steps exist.
    log = _build_log_with_steps(1, 2)
    w, handler, loop = _make_handler_with_loop(log, tmp_path)
    events_before = tuple(log.events)

    with patch("PySide6.QtWidgets.QMessageBox.question") as mock_question:
        result = handler.handle("/revise-history 5")

    assert result is None
    mock_question.assert_not_called()
    w.conversation.append_error.assert_called_once()
    assert "Only 2 step" in w.conversation.append_error.call_args[0][0]
    # Real log must be untouched.
    assert log.events == events_before


def test_revise_history_confirm_revises_and_persists(tmp_path: Path):
    from PySide6.QtWidgets import QMessageBox

    log = _build_log_with_steps(1, 2)
    w, handler, loop = _make_handler_with_loop(log, tmp_path)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ) as mock_question, patch("agent.session_store.write_session") as mock_write:
        result = handler.handle("/revise-history 1")

    assert result is None
    mock_question.assert_called_once()
    mock_write.assert_called_once()
    assert loop.sync_calls == 1
    w.conversation.clear.assert_called_once()
    # Step 2 removed, step 1 remains.
    remaining_types = [e.type for e in log.events]
    assert ev.STEP_END in remaining_types
    assert len(log.derive_messages()) > 0
    # Success message shown.
    info_msgs = [c.args[0] for c in w.conversation.append_info.call_args_list]
    assert any("Removed 1 step" in m for m in info_msgs)


def test_revise_history_cancel_leaves_log_untouched(tmp_path: Path):
    log = _build_log_with_steps(1, 2)
    w, handler, loop = _make_handler_with_loop(log, tmp_path)
    events_before = tuple(log.events)

    from PySide6.QtWidgets import QMessageBox
    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ) as mock_question, patch("agent.session_store.write_session") as mock_write:
        result = handler.handle("/revise-history 1")

    assert result is None
    mock_question.assert_called_once()
    mock_write.assert_not_called()
    assert loop.sync_calls == 0
    w.conversation.clear.assert_not_called()
    assert log.events == events_before
    info_msgs = [c.args[0] for c in w.conversation.append_info.call_args_list]
    assert any("Revision cancelled" in m for m in info_msgs)


def _build_log_with_image_step() -> SessionLog:
    """One turn, two steps; step 1's assistant message carries an image
    content block. Reviewing 1 step (removing step 2) retains step 1 so its
    image block goes through re-render's image-handling branch."""
    log = SessionLog()
    log.append(ev.TURN_START, {"turn": 1})
    log.append(
        ev.USER_MESSAGE,
        {"turn": 1, "step": 0, "role": "user", "content": "show me a picture"},
        surface_op="append",
    )
    log.append(ev.STEP_START, {"turn": 1, "step": 1})
    log.append(ev.TOOL_CALL, {"turn": 1, "step": 1, "call_id": "call_1_1", "name": "tool_1", "input": {}})
    log.append(
        ev.TOOL_RESULT,
        {"turn": 1, "step": 1, "call_id": "call_1_1", "content": "result 1"},
        surface_op="append",
    )
    log.append(
        ev.ASSISTANT_MESSAGE,
        {
            "turn": 1,
            "step": 1,
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Here is a picture"},
                    {"type": "dagi_image", "url": "data:image/png;base64,xxxx"},
                ],
            },
        },
        surface_op="append",
    )
    log.append(ev.STEP_END, {"turn": 1, "step": 1})
    log.append(ev.STEP_START, {"turn": 1, "step": 2})
    log.append(ev.TOOL_CALL, {"turn": 1, "step": 2, "call_id": "call_1_2", "name": "tool_2", "input": {}})
    log.append(
        ev.TOOL_RESULT,
        {"turn": 1, "step": 2, "call_id": "call_1_2", "content": "result 2"},
        surface_op="append",
    )
    log.append(
        ev.ASSISTANT_MESSAGE,
        {"turn": 1, "step": 2, "message": {"role": "assistant", "content": "Response t1s2"}},
        surface_op="append",
    )
    log.append(ev.STEP_END, {"turn": 1, "step": 2})
    log.append(ev.TURN_END, {"turn": 1, "reason": ev.reason_completed()})
    return log


def test_revise_history_rerender_shows_image_placeholder(tmp_path: Path):
    """A retained step containing an image content block must re-render as
    the '[image]' placeholder text (exercises the image branch of re-render)."""
    log = _build_log_with_image_step()

    w, handler, loop = _make_handler_with_loop(log, tmp_path)

    from PySide6.QtWidgets import QMessageBox
    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ), patch("agent.session_store.write_session"):
        handler.handle("/revise-history 1")

    assistant_msgs = [c.args[0] for c in w.conversation.append_assistant.call_args_list]
    assert any("[image]" in m and "Here is a picture" in m for m in assistant_msgs)


def test_revise_history_rerender_shows_tool_role_via_append_info(tmp_path: Path):
    """A retained step's tool-role message must re-render via append_info
    (the role == 'tool' branch added during review). Every step's
    tool/result event projects to a role="tool" surface message (see
    agent/session_surface.py::project_event), so step 1's tool result —
    retained when step 2 is revised away — exercises this branch."""
    log = _build_log_with_steps(1, 2)

    w, handler, loop = _make_handler_with_loop(log, tmp_path)

    from PySide6.QtWidgets import QMessageBox
    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ), patch("agent.session_store.write_session"):
        handler.handle("/revise-history 1")

    info_msgs = [c.args[0] for c in w.conversation.append_info.call_args_list]
    assert any("tool result" in m for m in info_msgs)
