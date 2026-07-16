"""tests/test_subagent_runner.py — Unit tests for tools/_subagent_runner.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from tools import _subagent_runner
from tools._subagent_runner import _poll_until, _SubagentState


def _make_state(tmp_path: Path, poll_side_effect) -> tuple[_SubagentState, MagicMock]:
    proc = MagicMock()
    proc.pid = 4242
    proc.poll.side_effect = poll_side_effect
    handoff_path = tmp_path / "worker_ab12cd34.md"
    state = _SubagentState(
        proc=proc,
        handoff_path=handoff_path,
        task_file=tmp_path / "task.txt",
        subagent_type="worker",
        on_event=None,
    )
    (tmp_path / "task.txt").write_text("task", encoding="utf-8")
    return state, proc


class TestEscalationDetection:
    def test_escalation_file_present_terminates_process_and_returns_escalated(self, tmp_path):
        escalation_path = tmp_path / "worker_ab12cd34_escalation.md"
        escalation_path.write_text(
            "# Escalation\n\n## Question\nWhich lib?\n\n## Context\nAmbiguous.\n",
            encoding="utf-8",
        )
        # Process never exits on its own — only the escalation check should end the poll.
        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)

        result = _poll_until(state, extra_seconds=10)

        assert result["status"] == "escalated"
        assert "Which lib?" in result["escalation"]
        proc.terminate.assert_called_once()

    def test_escalation_detected_even_when_process_still_alive_within_first_tick(self, tmp_path):
        escalation_path = tmp_path / "worker_ab12cd34_escalation.md"
        escalation_path.write_text("# Escalation\n\n## Question\nQ\n\n## Context\nC\n", encoding="utf-8")
        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)

        result = _poll_until(state, extra_seconds=1)

        assert result["status"] == "escalated"
        # Escalation must be detected before any proc.poll() call happens.
        proc.poll.assert_not_called()

    def test_terminate_timeout_falls_back_to_kill(self, tmp_path):
        import subprocess as sp
        escalation_path = tmp_path / "worker_ab12cd34_escalation.md"
        escalation_path.write_text("# Escalation\n\n## Question\nQ\n\n## Context\nC\n", encoding="utf-8")
        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)
        proc.wait.side_effect = sp.TimeoutExpired(cmd="x", timeout=5)

        result = _poll_until(state, extra_seconds=10)

        assert result["status"] == "escalated"
        proc.kill.assert_called_once()

    def test_no_escalation_file_falls_through_to_normal_ok_path(self, tmp_path):
        state, proc = _make_state(tmp_path, poll_side_effect=[None, 0])
        state.handoff_path.write_text("# Handoff\n\ndone\n", encoding="utf-8")

        result = _poll_until(state, extra_seconds=10)

        assert result["status"] == "ok"

    def test_malformed_escalation_file_returns_error_not_crash(self, tmp_path, monkeypatch):
        escalation_path = tmp_path / "worker_ab12cd34_escalation.md"
        escalation_path.write_bytes(b"\xff\xfe\x00\x01")  # invalid utf-8
        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)

        result = _poll_until(state, extra_seconds=10)

        assert result["status"] == "error"
        assert "escalation" in result["message"].lower()


class TestForceKillActiveSubagents:
    def test_force_kill_calls_kill_process_tree_on_every_active_proc(self, tmp_path, monkeypatch):
        killed_procs = []
        monkeypatch.setattr(
            "tools._subagent_runner.kill_process_tree",
            lambda proc: killed_procs.append(proc),
        )
        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)
        with _subagent_runner._active_lock:
            _subagent_runner._active[proc.pid] = state

        try:
            killed_count = _subagent_runner.force_kill_active_subagents()
        finally:
            with _subagent_runner._active_lock:
                _subagent_runner._active.pop(proc.pid, None)

        assert killed_count == 1
        assert killed_procs == [proc]

    def test_force_kill_returns_zero_when_no_active_subagents(self):
        assert _subagent_runner.force_kill_active_subagents() == 0
