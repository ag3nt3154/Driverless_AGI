"""pyside_gui/tests/test_rpa_cards.py — halt card parsing and wiring (Subtask 19).

Three layers, per the Subtask 19 requirements:
  1. `rpa_cards.parse_rpa_halt` — pure, no Qt.
  2. `AgentSession` wiring: a halted tool_ended -> `append_rpa_halt_card`; the
     Repair button -> `dispatch_workflow_action` against the owning session,
     refused while busy/pending ask exactly like the Workflows view.
  3. The real page: `appendRpaHaltCard` renders a card with three actions, and
     the bridge slot (`window._dagi.rpaRepair`) emits `rpa_repair_requested`.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pyside_gui  # noqa: F401 - register DLL paths before Qt imports

from pyside_gui.conversation import ConversationView
from pyside_gui.rpa_cards import HaltInfo, parse_rpa_halt
from pyside_gui.tests.session_stub import StubSession
from pyside_gui.tests.test_conversation_reasoning import evaluate, view  # noqa: F401

_SUFFIX = "Offer the Admiral a repair (rpa_repair) — do not start it unasked."


def _halt_line(step: str, reason: str, run_dir) -> str:
    return f"Step `{step}` halted: {reason}. Evidence: {run_dir}. {_SUFFIX}"


# ---- 1. parser --------------------------------------------------------------


def test_parses_a_halted_rpa_run_result(tmp_path):
    run_dir = tmp_path / "demo" / "runs" / "20261012T000000Z"
    result = (
        "opened: w:1 | App | Title\nstatus: halted\nsteps: 2\n"
        "  step_a: ok\n  step_b: halted\n"
        + _halt_line("step_b", "no locator matched", run_dir)
    )
    info = parse_rpa_halt("rpa_run", result)
    assert info == HaltInfo(
        name="demo", step="step_b", reason="no locator matched",
        run_dir=run_dir, screenshot=None,
    )


def test_parses_halt_with_a_screenshot(tmp_path):
    run_dir = tmp_path / "demo" / "runs" / "20261012T000000Z"
    run_dir.mkdir(parents=True)
    (run_dir / "halt.png").write_bytes(b"\x89PNG")
    result = "status: halted\n" + _halt_line("step_b", "window vanished", run_dir)
    info = parse_rpa_halt("rpa_run", result)
    assert info.screenshot == run_dir / "halt.png"


def test_reason_containing_evidence_like_text_splits_on_the_last_separator(tmp_path):
    run_dir = tmp_path / "demo" / "runs" / "20261012T000000Z"
    reason = 'Element not found. Evidence: "nope" was checked first'
    result = "status: halted\n" + _halt_line("step_b", reason, run_dir)
    info = parse_rpa_halt("rpa_run", result)
    assert info.reason == reason
    assert info.run_dir == run_dir


def test_rpa_patch_result_carries_the_same_halt_line(tmp_path):
    run_dir = tmp_path / "demo" / "runs" / "20261012T000000Z"
    result = (
        "patched 'demo':\n--- workflow.yaml\n+++ workflow.yaml\n"
        "opened: w:1 | App | Title\nstatus: halted\nsteps: 1\n  step_c: halted\n"
        + _halt_line("step_c", "second halt after the patch", run_dir)
    )
    info = parse_rpa_halt("rpa_patch", result)
    assert info.name == "demo"
    assert info.step == "step_c"
    assert info.reason == "second halt after the patch"


@pytest.mark.parametrize("tool_name, result", [
    ("rpa_run", "status: ok\nsteps: 1\n  step_a: ok"),
    ("rpa_run", "Stopped: the Admiral pressed Esc during step `step_a`. This was a "
                "deliberate stop, not a failure — do not offer a repair or re-run unless asked."),
    ("rpa_run", "Error (RpaError): unknown workflow 'demo'"),
    ("rpa_patch", "not patched"),
    ("some_other_tool", "Step `x` halted: y. Evidence: z. " + _SUFFIX),
    ("rpa_run", None),
])
def test_non_halt_results_return_none(tool_name, result):
    assert parse_rpa_halt(tool_name, result) is None


# ---- 2. session wiring -------------------------------------------------------


def test_halted_tool_end_appends_a_halt_card(tmp_path):
    session = StubSession()
    run_dir = tmp_path / "demo" / "runs" / "20261012T000000Z"
    result = "status: halted\n" + _halt_line("step_b", "no locator matched", run_dir)

    session._on_tool_ended_rpa("rpa_run", result)

    session._conversation.append_rpa_halt_card.assert_called_once()
    info = session._conversation.append_rpa_halt_card.call_args[0][0]
    assert info.name == "demo"
    assert info.step == "step_b"


def test_ok_tool_end_appends_no_card():
    session = StubSession()
    session._on_tool_ended_rpa("rpa_run", "status: ok\nsteps: 1\n  a: ok")
    session._conversation.append_rpa_halt_card.assert_not_called()


def test_repair_button_dispatches_to_the_owning_session():
    session = StubSession()
    session._on_input_submitted = MagicMock()

    session._on_rpa_repair_requested("demo")

    session._on_input_submitted.assert_called_once_with(
        "Repair workflow `demo` (rpa_repair)."
    )
    session._conversation.append_error.assert_not_called()


def test_repair_button_refused_while_busy():
    session = StubSession()
    session._worker = SimpleNamespace(is_alive=lambda: True)
    session._on_input_submitted = MagicMock()

    session._on_rpa_repair_requested("demo")

    session._conversation.append_error.assert_called_once()
    session._on_input_submitted.assert_not_called()


def test_repair_button_refused_while_pending_ask():
    session = StubSession()
    session._pending_ask = object()
    session._on_input_submitted = MagicMock()

    session._on_rpa_repair_requested("demo")

    session._conversation.append_error.assert_called_once()
    session._on_input_submitted.assert_not_called()


# ---- 3. the real page ---------------------------------------------------------


def test_bridge_slot_emits_rpa_repair_requested():
    convo = ConversationView()
    received = []
    convo.rpa_repair_requested.connect(received.append)

    convo._page_bridge.rpaRepair("demo")

    assert received == ["demo"]
    convo.close()
    convo.deleteLater()


def test_halt_card_renders_with_three_actions_and_no_screenshot_link(view):
    info = HaltInfo(
        name="demo", step="click_x", reason="no locator matched",
        run_dir=Path("somewhere"), screenshot=None,
    )
    view.append_rpa_halt_card(info)
    state = evaluate(view, """
        const card = document.querySelector('.halt-card');
        return {
            header: card.querySelector('.halt-header').textContent,
            step: card.querySelector('.halt-step code').textContent,
            reason: card.querySelector('.halt-reason').textContent,
            buttons: card.querySelectorAll('.halt-actions .halt-btn').length,
            screenshotHidden: card.querySelector('.halt-screenshot').hidden,
            screenshotIsLink: card.querySelector('.halt-screenshot').tagName === 'A',
        };
    """)
    assert state["step"] == "click_x"
    assert state["reason"] == "no locator matched"
    assert state["buttons"] == 3
    assert state["screenshotHidden"] is True
    assert "demo" in state["header"]


def test_halt_card_shows_a_screenshot_link_when_present(view, tmp_path):
    shot = tmp_path / "halt.png"
    shot.write_bytes(b"\x89PNG")
    info = HaltInfo(name="demo", step="s1", reason="r", run_dir=tmp_path, screenshot=shot)
    view.append_rpa_halt_card(info)
    state = evaluate(view, """
        const a = document.querySelector('.halt-screenshot');
        return {tag: a.tagName, hasHref: a.hasAttribute('href'), hidden: a.hidden};
    """)
    assert state == {"tag": "A", "hasHref": True, "hidden": False}


def test_dismiss_removes_the_card(view):
    info = HaltInfo(name="demo", step="s1", reason="r", run_dir=Path("x"), screenshot=None)
    view.append_rpa_halt_card(info)
    evaluate(view, "document.querySelector('.halt-dismiss').click(); return 1;")
    assert evaluate(view, "return document.querySelectorAll('.halt-card').length;") == 0
