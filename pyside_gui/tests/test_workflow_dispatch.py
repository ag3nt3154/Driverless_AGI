"""pyside_gui/tests/test_workflow_dispatch.py — Workflows-view action -> active session (Subtask 18).

Building a full `DagiMainWindow` for this is impractical (it needs a real
`AgentConfig`, project folder and worker thread machinery); per the Subtask 18
acceptance criteria, the busy/pending-ask refusal logic lives in a small pure
function (`workflow_action_refusal`) that is unit tested directly, and
`dispatch_workflow_action` (also tested here) is the thin glue that calls it
against the active session and either shows the refusal or dispatches the
message exactly like typed input.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from pyside_gui._dispatch import dispatch_workflow_action, workflow_action_refusal


def _session(*, busy=False, waiting=False):
    session = MagicMock()
    session.busy = busy
    session.waiting = waiting
    return session


def test_refusal_none_when_idle():
    assert workflow_action_refusal(_session()) is None


def test_refusal_when_busy():
    assert workflow_action_refusal(_session(busy=True)) == (
        "dagi is busy — try again when the turn ends"
    )


def test_refusal_when_pending_ask():
    assert workflow_action_refusal(_session(waiting=True)) == (
        "dagi is busy — try again when the turn ends"
    )


def test_dispatch_refuses_while_busy_and_never_sends():
    win = MagicMock()
    win._active = _session(busy=True)

    dispatch_workflow_action(win, "Run workflow `x` (rpa_run).")

    win._active._conversation.append_error.assert_called_once_with(
        "dagi is busy — try again when the turn ends"
    )
    win._active._on_input_submitted.assert_not_called()


def test_dispatch_refuses_with_pending_ask_and_never_sends():
    win = MagicMock()
    win._active = _session(waiting=True)

    dispatch_workflow_action(win, "Approve workflow `x` (rpa_approve).")

    win._active._conversation.append_error.assert_called_once()
    win._active._on_input_submitted.assert_not_called()


def test_dispatch_sends_like_typed_input_when_free():
    win = MagicMock()
    win._active = _session()

    dispatch_workflow_action(win, "Verify workflow `x` (rpa_run with verify=true).")

    win._active._conversation.append_error.assert_not_called()
    win._active._on_input_submitted.assert_called_once_with(
        "Verify workflow `x` (rpa_run with verify=true)."
    )
