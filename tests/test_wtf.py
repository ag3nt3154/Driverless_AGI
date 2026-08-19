"""Parent-side orchestration for the inherited read-only ``/wtf`` subagent."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import session_events as sev
from agent.loop import AgentConfig, AgentLoop
from tools.subagent_api import SubagentResult


REPORT = """## Description
The worker cannot locate its configuration.

## Error Report
FileNotFoundError at startup.

## Suggested Fix
Use the configured project root.
"""


def _loop(tmp_path: Path) -> AgentLoop:
    config = AgentConfig(model="test", api_key="key", project_path=tmp_path)
    with patch("openai.OpenAI", return_value=MagicMock()):
        loop = AgentLoop(config)
    loop.log.append(sev.TURN_START, {"turn": 1})
    loop._log_user_message("user", "The worker failed to start.", "input")
    loop._close_turn(1, sev.reason_completed())
    return loop


def _result(path: Path, *, status: str = "ok", text: str = REPORT) -> SubagentResult:
    return SubagentResult(status, text, path, None, None, None, "wtf_branch")


def _capture_result(loop: AgentLoop, result: SubagentResult, captured: dict):
    def fake_run(**kwargs):
        captured.update(kwargs)
        captured["open_turn_at_fork"] = loop.log.open_turn
        captured["open_step_at_fork"] = loop.log.open_step
        kwargs["parent_context"].capture_fork(result.branch_id, kwargs["fork_mode"])
        return result

    return fake_run


def test_idle_wtf_appends_one_reference_in_a_dedicated_command_turn(tmp_path: Path) -> None:
    """Dropping the reference or injecting the report body loses a model-visible diagnosis."""
    loop = _loop(tmp_path)
    report_path = tmp_path / ".dagi" / "errors" / "wtf_branch.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(REPORT, encoding="utf-8")
    captured: dict = {}
    header = loop._messages[0]
    header_bytes = json.dumps(header, sort_keys=True).encode()

    with patch("agent.wtf.run_subagent", side_effect=_capture_result(loop, _result(report_path), captured)):
        result = loop.run_wtf(None)

    assert result.description == "The worker cannot locate its configuration."
    assert result.report_path == report_path.resolve()
    assert result.branch_id == "wtf_branch"
    assert captured["preset"] == "wtf"
    assert captured["parent_context"].capture_fork.__self__ is loop
    assert captured["parent_context"].get_surface_generation() == loop.log.surface.generation
    assert captured["fork_mode"] == "stable"
    assert captured["handoff_dir"] == tmp_path / ".dagi" / "errors"
    assert "inherited context" in captured["task"]
    assert captured["open_turn_at_fork"] is None
    assert loop.log.open_turn is None
    assert loop._messages[0] is header
    assert json.dumps(loop._messages[0], sort_keys=True).encode() == header_bytes
    references = [
        event for event in loop.log.events
        if event.type == sev.USER_MESSAGE and event.data.get("source") == "wtf"
    ]
    assert len(references) == 1
    reference = references[0].data["content"]
    assert "/wtf" in reference
    assert ".dagi/errors/wtf_branch.md" in reference
    assert "wtf_branch" in reference
    assert REPORT not in reference
    assert "FileNotFoundError at startup." not in reference
    assert loop.log.branch_event("wtf_branch") is not None


def test_described_wtf_preserves_the_hint_verbatim_in_task_and_reference(tmp_path: Path) -> None:
    """Normalizing a user hint would silently change the diagnostic requested."""
    loop = _loop(tmp_path)
    report_path = tmp_path / ".dagi" / "errors" / "wtf_branch.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(REPORT, encoding="utf-8")
    hint = "  inspect O'Reilly\nthen this exact line  "
    captured: dict = {}

    with patch("agent.wtf.run_subagent", side_effect=_capture_result(loop, _result(report_path), captured)):
        loop.run_wtf(hint)

    assert hint in captured["task"]
    reference = next(
        event.data["content"] for event in loop.log.events
        if event.type == sev.USER_MESSAGE and event.data.get("source") == "wtf"
    )
    assert f"/wtf {hint}" in reference


def test_paused_wtf_uses_the_open_safe_step_without_resuming_or_closing_it(tmp_path: Path) -> None:
    """Closing or resuming a paused task would race the normal agent loop."""
    loop = _loop(tmp_path)
    loop.log.append(sev.TURN_START, {"turn": 2})
    loop.log.append(sev.STEP_START, {"turn": 2, "step": 1})
    loop.pause()
    loop._pause_checkpoint.set()
    report_path = tmp_path / ".dagi" / "errors" / "wtf_branch.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(REPORT, encoding="utf-8")
    before_messages = [dict(message) for message in loop._messages]
    before_surface_bytes = json.dumps(loop._messages[1:], sort_keys=True).encode()
    before_message_objects = list(loop._messages[1:])
    header = loop._messages[0]
    header_bytes = json.dumps(header, sort_keys=True).encode()
    messages_list = loop._messages

    captured: dict = {}
    with patch("agent.wtf.run_subagent", side_effect=_capture_result(loop, _result(report_path), captured)):
        loop.run_wtf(None)

    assert (captured["open_turn_at_fork"], captured["open_step_at_fork"]) == (2, 1)
    assert loop.log.open_turn == 2
    assert loop.log.open_step == 1
    assert not loop._pause_event.is_set()
    assert loop._pause_checkpoint.is_set()
    assert loop._messages is messages_list
    assert loop._messages[0] is header
    assert json.dumps(loop._messages[0], sort_keys=True).encode() == header_bytes
    assert loop._messages[1:-1] == before_messages[1:]
    assert json.dumps(loop._messages[1:-1], sort_keys=True).encode() == before_surface_bytes
    assert all(before is after for before, after in zip(before_message_objects, loop._messages[1:-1]))


def test_paused_wtf_failure_preserves_checkpoint_and_parent_surface(tmp_path: Path) -> None:
    """A failed child must leave a paused parent ready for its normal resume path."""
    loop = _loop(tmp_path)
    loop.log.append(sev.TURN_START, {"turn": 2})
    loop.log.append(sev.STEP_START, {"turn": 2, "step": 1})
    loop.pause()
    loop._pause_checkpoint.set()
    report_path = tmp_path / ".dagi" / "errors" / "wtf_branch.md"
    report_path.parent.mkdir(parents=True)
    before_messages = loop._messages
    before_message_objects = list(loop._messages)
    before_surface = loop.log.surface.nodes
    before_generation = loop.log.surface.generation
    before_bytes = json.dumps(loop._messages, sort_keys=True).encode()

    with patch(
        "agent.wtf.run_subagent",
        side_effect=_capture_result(
            loop,
            _result(report_path, status="timeout", text=""),
            {},
        ),
    ):
        with pytest.raises(RuntimeError, match="status: timeout"):
            loop.run_wtf(None)

    assert loop._messages is before_messages
    assert all(before is after for before, after in zip(before_message_objects, loop._messages))
    assert json.dumps(loop._messages, sort_keys=True).encode() == before_bytes
    assert loop.log.surface.nodes == before_surface
    assert loop.log.surface.generation == before_generation
    assert loop.log.open_turn == 2
    assert loop.log.open_step == 1
    assert loop._pause_event.is_set() is False
    assert loop._pause_checkpoint.is_set()
    assert not any(event.data.get("source") == "wtf" for event in loop.log.events)


def test_wtf_rejects_missing_conversation_before_spawning(tmp_path: Path) -> None:
    """Forking a header-only session gives the child no diagnostic context."""
    config = AgentConfig(model="test", api_key="key", project_path=tmp_path)
    with patch("openai.OpenAI", return_value=MagicMock()):
        loop = AgentLoop(config)

    with patch("agent.wtf.run_subagent") as run_subagent:
        with pytest.raises(RuntimeError, match="active conversation"):
            loop.run_wtf(None)

    run_subagent.assert_not_called()
    assert loop.log.surface.nodes == ()


@pytest.mark.parametrize(
    "outcome,status,text,raises",
    [
        ("timeout", "timeout", "", "status: timeout"),
        ("empty", "ok", "", "malformed"),
        ("truncated", "ok", REPORT.split("## Suggested Fix", maxsplit=1)[0], "malformed"),
        ("malformed", "ok", "unstructured handoff", "malformed"),
        ("write_error", "error", REPORT, "status: error"),
        ("stale", "stale", REPORT, "status: stale"),
    ],
)
def test_wtf_failure_matrix_preserves_surface_without_reference(
    tmp_path: Path, outcome: str, status: str, text: str, raises: str,
) -> None:
    """Every failed outcome must not create a false diagnostic link."""
    loop = _loop(tmp_path)
    report_path = tmp_path / ".dagi" / "errors" / "wtf_branch.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(text, encoding="utf-8")
    before_messages = loop._messages
    before_objects = list(loop._messages)
    before_surface = loop.log.surface.nodes
    before_generation = loop.log.surface.generation
    before_bytes = json.dumps(loop._messages, sort_keys=True).encode()

    with patch(
        "agent.wtf.run_subagent",
        side_effect=_capture_result(loop, _result(report_path, status=status, text=text), {}),
    ):
        with pytest.raises(RuntimeError, match=raises):
            loop.run_wtf(None)

    assert loop._messages is before_messages, outcome
    assert all(before is after for before, after in zip(before_objects, loop._messages))
    assert json.dumps(loop._messages, sort_keys=True).encode() == before_bytes
    assert loop.log.surface.nodes == before_surface
    assert loop.log.surface.generation == before_generation
    assert not any(event.data.get("source") == "wtf" for event in loop.log.events)


def test_wtf_fork_error_preserves_surface_without_branch_reference(tmp_path: Path) -> None:
    """A fork that cannot be captured must fail before adding any child metadata."""
    loop = _loop(tmp_path)
    before_messages = loop._messages
    before_surface = loop.log.surface.nodes
    before_generation = loop.log.surface.generation
    before_bytes = json.dumps(loop._messages, sort_keys=True).encode()

    with patch("agent.wtf.run_subagent", side_effect=RuntimeError("fork failed")):
        with pytest.raises(RuntimeError, match="fork failed"):
            loop.run_wtf(None)

    assert loop._messages is before_messages
    assert json.dumps(loop._messages, sort_keys=True).encode() == before_bytes
    assert loop.log.surface.nodes == before_surface
    assert loop.log.surface.generation == before_generation
    assert loop.log.branch_event("wtf_branch") is None
    assert not any(event.data.get("source") == "wtf" for event in loop.log.events)


def test_wtf_rejects_malformed_or_missing_handoff_without_surface_mutation(tmp_path: Path) -> None:
    """A report path is not useful unless it points at a complete structured diagnosis."""
    loop = _loop(tmp_path)
    missing = tmp_path / ".dagi" / "errors" / "missing.md"
    before = [dict(message) for message in loop._messages]

    with patch("agent.wtf.run_subagent", side_effect=_capture_result(loop, _result(missing), {})):
        with pytest.raises(RuntimeError, match="handoff"):
            loop.run_wtf(None)

    assert loop._messages == before


def test_wtf_rejects_a_surface_generation_change_after_the_child_returns(tmp_path: Path) -> None:
    """Appending after compaction would bind the child report to the wrong prefix."""
    loop = _loop(tmp_path)
    report_path = tmp_path / ".dagi" / "errors" / "wtf_branch.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(REPORT, encoding="utf-8")
    def stale_run(**kwargs):
        kwargs["parent_context"].capture_fork("wtf_branch", "stable")
        turn = loop.log.next_turn()
        loop.log.append(sev.TURN_START, {"turn": turn})
        node = loop.log.surface.nodes[0]
        loop.log.append(
            sev.CONTEXT_COMPACTION,
            {"summary": "replacement", "removed": 1, "generation": 1},
            surface_op=("replace", node, node),
            source_seqs=[node],
        )
        loop._close_turn(turn, sev.reason_completed())
        return _result(report_path)

    with patch("agent.wtf.run_subagent", side_effect=stale_run):
        with pytest.raises(RuntimeError, match="stale"):
            loop.run_wtf(None)

    assert not any(event.data.get("source") == "wtf" for event in loop.log.events)
