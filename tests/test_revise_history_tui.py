"""tests/test_revise_history_tui.py — TUI revise-history modal and command."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import session_events as ev
from agent.session_log import SessionLog, StepInfo
from tui.commands import SlashCommandsMixin
from tui.conversation import ConversationPane


class TestReviseConfirmScreen:
    def test_formats_single_step_summary(self):
        from tui.revise_history import format_step_summaries
        infos = [
            StepInfo(step_number=3, turn=2, tool_names=["read_file", "edit_file"],
                     assistant_snippet="I've updated the config to use the new...",
                     event_range=(10, 15)),
        ]
        text = format_step_summaries(infos)
        assert "Step 3" in text
        assert "turn 2" in text
        assert "read_file" in text
        assert "edit_file" in text
        assert "I've updated the config" in text

    def test_formats_multiple_step_summaries(self):
        from tui.revise_history import format_step_summaries
        infos = [
            StepInfo(step_number=3, turn=2, tool_names=["edit_file"],
                     assistant_snippet="Edited config...", event_range=(10, 15)),
            StepInfo(step_number=2, turn=2, tool_names=["grep"],
                     assistant_snippet="Found 3 matches...", event_range=(5, 9)),
        ]
        text = format_step_summaries(infos)
        assert "Step 3" in text
        assert "Step 2" in text

    def test_formats_step_with_no_tools(self):
        from tui.revise_history import format_step_summaries
        infos = [
            StepInfo(step_number=1, turn=1, tool_names=[],
                     assistant_snippet="Hello!", event_range=(1, 3)),
        ]
        text = format_step_summaries(infos)
        assert "Step 1" in text
        assert "Hello!" in text


# ── /revise-history handler (SlashCommandsMixin._cmd_revise_history) ────────


def _build_log_with_steps(n_turns: int, steps_per_turn: int) -> SessionLog:
    """Build a SessionLog with the given number of turns, each with the given
    number of steps (tool/call, tool/result, assistant/message per step).

    Mirrors tests/test_session_log_revise.py::_build_log_with_steps.
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


def _build_log_with_image_step() -> SessionLog:
    """One turn, two steps; step 1's assistant message carries an image
    content block. Revising 1 step (removing step 2) retains step 1, so its
    image block goes through the re-render's image-handling branch."""
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


class _Conversation:
    def __init__(self) -> None:
        self.info: list[str] = []
        self.errors: list[str] = []
        self.written: list = []
        self.assistant: list[str] = []
        self.cleared = 0

    def append_info(self, message: str) -> None:
        self.info.append(message)

    def append_error(self, message: str) -> None:
        self.errors.append(message)

    def write(self, renderable) -> None:
        self.written.append(renderable)

    def append_assistant(self, text: str) -> None:
        self.assistant.append(text)

    def clear(self) -> None:
        self.cleared += 1


class _Worker:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _Tracker:
    def __init__(self, path: Path) -> None:
        self._path = path


class _FakeLoop:
    """Minimal stand-in for AgentLoop exposing only what _cmd_revise_history touches."""

    def __init__(self, log: SessionLog, tracker_path: Path) -> None:
        self.log = log
        self.tracker = _Tracker(tracker_path)
        self.sync_calls = 0

    def _sync_messages(self) -> None:
        self.sync_calls += 1


class _App(SlashCommandsMixin):
    """Lightweight stand-in for DagiApp: mixes in SlashCommandsMixin directly
    rather than driving a full Textual App/pilot, per the fallback plan for
    testing a mixin method in isolation. push_screen is stubbed to invoke the
    modal's callback immediately with a canned confirm/cancel answer, instead
    of opening a real ReviseConfirmScreen modal."""

    def __init__(self, loop=None, *, worker_alive: bool = False, confirm_result: bool = True) -> None:
        self.conv = _Conversation()
        self._active_loop = loop
        self._worker = _Worker(worker_alive) if worker_alive else None
        self._confirm_result = confirm_result
        self.pushed_screens: list = []

    def query_one(self, selector, *_args):
        if selector is ConversationPane:
            return self.conv
        raise AssertionError(f"Unexpected query: {selector!r}")

    def push_screen(self, screen, callback=None) -> None:
        self.pushed_screens.append(screen)
        if callback is not None:
            callback(self._confirm_result)


def _make_app_with_loop(log: SessionLog, tmp_path: Path, **kwargs) -> tuple[_App, _FakeLoop]:
    loop = _FakeLoop(log, tmp_path / "session.jsonl")
    app = _App(loop, **kwargs)
    return app, loop


class TestCmdReviseHistory:
    def test_no_active_loop_shows_info(self) -> None:
        app = _App()
        app._cmd_revise_history(None)
        assert "Nothing to revise" in app.conv.info[-1]

    def test_blocked_while_worker_alive(self, tmp_path: Path) -> None:
        log = _build_log_with_steps(1, 1)
        app, loop = _make_app_with_loop(log, tmp_path, worker_alive=True)
        events_before = tuple(log.events)

        app._cmd_revise_history(None)

        assert "Cannot revise" in app.conv.info[-1]
        assert app.pushed_screens == []
        assert log.events == events_before

    def test_rejects_non_numeric_argument(self, tmp_path: Path) -> None:
        log = _build_log_with_steps(1, 1)
        app, loop = _make_app_with_loop(log, tmp_path)
        events_before = tuple(log.events)

        app._cmd_revise_history("abc")

        assert "Invalid argument" in app.conv.info[-1]
        assert log.events == events_before
        assert app.pushed_screens == []

    @pytest.mark.parametrize("arg", ["0", "-1"])
    def test_rejects_non_positive_n(self, arg: str, tmp_path: Path) -> None:
        log = _build_log_with_steps(1, 1)
        app, loop = _make_app_with_loop(log, tmp_path)
        events_before = tuple(log.events)

        app._cmd_revise_history(arg)

        assert "N must be at least 1" in app.conv.info[-1]
        assert log.events == events_before
        assert app.pushed_screens == []

    def test_errors_when_too_many_steps_requested(self, tmp_path: Path) -> None:
        # Only 2 steps exist.
        log = _build_log_with_steps(1, 2)
        app, loop = _make_app_with_loop(log, tmp_path)
        events_before = tuple(log.events)

        app._cmd_revise_history("5")

        assert "Only 2 step" in app.conv.info[-1]
        assert app.pushed_screens == []
        assert log.events == events_before

    def test_confirm_revises_and_persists(self, tmp_path: Path, monkeypatch) -> None:
        log = _build_log_with_steps(1, 2)
        app, loop = _make_app_with_loop(log, tmp_path, confirm_result=True)
        write_calls: list = []
        monkeypatch.setattr(
            "agent.session_store.write_session",
            lambda path, events: write_calls.append((path, list(events))),
        )

        app._cmd_revise_history("1")

        assert len(app.pushed_screens) == 1
        assert write_calls, "write_session must be called to persist the revision"
        assert loop.sync_calls == 1
        assert app.conv.cleared == 1
        remaining_types = [e.type for e in log.events]
        assert ev.STEP_END in remaining_types
        assert len(log.derive_messages()) > 0
        assert any("Removed 1 step" in m for m in app.conv.info)

    def test_cancel_leaves_log_untouched(self, tmp_path: Path, monkeypatch) -> None:
        log = _build_log_with_steps(1, 2)
        app, loop = _make_app_with_loop(log, tmp_path, confirm_result=False)
        events_before = tuple(log.events)
        write_calls: list = []
        monkeypatch.setattr(
            "agent.session_store.write_session",
            lambda path, events: write_calls.append((path, list(events))),
        )

        app._cmd_revise_history("1")

        assert write_calls == []
        assert loop.sync_calls == 0
        assert app.conv.cleared == 0
        assert log.events == events_before
        assert any("Revision cancelled" in m for m in app.conv.info)

    def test_rerender_shows_image_placeholder(self, tmp_path: Path, monkeypatch) -> None:
        """A retained step containing an image content block must re-render
        as the '[image]' placeholder text."""
        log = _build_log_with_image_step()
        app, loop = _make_app_with_loop(log, tmp_path, confirm_result=True)
        monkeypatch.setattr("agent.session_store.write_session", lambda path, events: None)

        app._cmd_revise_history("1")

        assert any(
            "[image]" in text and "Here is a picture" in text for text in app.conv.assistant
        )

    def test_rerender_shows_tool_role_via_append_info(self, tmp_path: Path, monkeypatch) -> None:
        """A retained step's tool-role message must re-render via
        append_info (the role == "tool" branch). Every step's tool/result
        event projects to a role="tool" surface message, so step 1's tool
        result — retained when step 2 is revised away — exercises it."""
        log = _build_log_with_steps(1, 2)
        app, loop = _make_app_with_loop(log, tmp_path, confirm_result=True)
        monkeypatch.setattr("agent.session_store.write_session", lambda path, events: None)

        app._cmd_revise_history("1")

        assert any("tool result" in text for text in app.conv.info)
