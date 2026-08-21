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


class TestUnverifiedHandoffDetection:
    def test_handoff_with_unverified_flag_returns_ok_unverified(self, tmp_path):
        state, proc = _make_state(tmp_path, poll_side_effect=[0])
        state.handoff_path.write_text("# Handoff\n\nscraped\n", encoding="utf-8")
        flag_path = tmp_path / "worker_ab12cd34_unverified.flag"
        flag_path.write_text("", encoding="utf-8")

        result = _poll_until(state, extra_seconds=10)

        assert result["status"] == "ok_unverified"
        assert result["handoff"] == str(state.handoff_path)

    def test_handoff_without_unverified_flag_returns_ok(self, tmp_path):
        state, proc = _make_state(tmp_path, poll_side_effect=[0])
        state.handoff_path.write_text("# Handoff\n\ndone\n", encoding="utf-8")

        result = _poll_until(state, extra_seconds=10)

        assert result["status"] == "ok"
        assert result["handoff"] == str(state.handoff_path)


class TestForkContextCleanup:
    def test_fork_context_path_stored_on_state(self, tmp_path):
        """When --fork-context is in extra_argv, state.fork_context_path is set."""
        from tools._subagent_runner import _SubagentState
        from pathlib import Path

        fc_path = tmp_path / "fork_ctx.json"
        fc_path.write_text('{"version": 1}', encoding="utf-8")

        state = _SubagentState(
            proc=None,  # type: ignore
            handoff_path=tmp_path / "handoff.md",
            task_file=tmp_path / "task.txt",
            subagent_type="compact",
            on_event=None,
            fork_context_path=fc_path,
        )
        assert state.fork_context_path == fc_path

    def test_fork_context_path_none_by_default(self, tmp_path):
        """_SubagentState.fork_context_path defaults to None."""
        from tools._subagent_runner import _SubagentState

        state = _SubagentState(
            proc=None,  # type: ignore
            handoff_path=tmp_path / "handoff.md",
            task_file=tmp_path / "task.txt",
            subagent_type="compact",
            on_event=None,
        )
        assert state.fork_context_path is None

    def test_active_state_reports_fork_context_ownership(self, tmp_path):
        """The API can distinguish registered runner ownership from spawn failure."""
        from tools import _subagent_runner as runner

        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)
        context_path = tmp_path / "fork_ctx.json"
        context_path.write_text('{"version": 2}', encoding="utf-8")
        state.fork_context_path = context_path
        with runner._active_lock:
            runner._active[proc.pid] = state

        try:
            assert runner.owns_fork_context_path(context_path) is True
            assert runner.owns_fork_context_path(tmp_path / "other.json") is False
        finally:
            with runner._active_lock:
                runner._active.pop(proc.pid, None)

    def test_fork_context_parsed_from_extra_argv(self, tmp_path):
        """run_subagent parses --fork-context from extra_argv and stores it on state."""
        from unittest.mock import MagicMock, patch
        import subprocess
        from tools import _subagent_runner as runner

        fc_path = tmp_path / "fork_ctx.json"
        fc_path.write_text('{"version": 1}', encoding="utf-8")
        handoff_path = tmp_path / "handoff.md"
        task_file_content = "task content"

        captured_state = []

        def capturing_poll_until(state, extra_seconds):
            captured_state.append(state)
            state.task_file.unlink(missing_ok=True)
            return {"status": "error", "message": "no handoff"}

        fake_proc = MagicMock(spec=subprocess.Popen)
        fake_proc.stdout = iter([])
        fake_proc.pid = 99999

        with patch("tools._subagent_runner.subprocess.Popen", return_value=fake_proc):
            with patch("tools._subagent_runner._poll_until", side_effect=capturing_poll_until):
                with patch("tools._subagent_runner._active", {}):
                    runner.run_subagent(
                        subagent_type="compact",
                        task=task_file_content,
                        project_path=tmp_path,
                        handoff_path=handoff_path,
                        timeout=5.0,
                        extra_argv=["--fork-context", str(fc_path)],
                    )

        assert len(captured_state) == 1
        assert captured_state[0].fork_context_path == fc_path

    def test_fork_context_deleted_on_terminal_exit(self, tmp_path):
        """Fork-context file is deleted when subprocess exits (no handoff written)."""
        from unittest.mock import MagicMock, patch
        import subprocess
        from tools import _subagent_runner as runner

        fc_path = tmp_path / "fork_ctx.json"
        fc_path.write_text('{"version": 1}', encoding="utf-8")
        handoff_path = tmp_path / "handoff.md"

        fake_proc = MagicMock(spec=subprocess.Popen)
        fake_proc.stdout = iter([])
        fake_proc.pid = 99999
        fake_proc.poll.return_value = 1  # process exited immediately
        fake_proc.wait.return_value = None

        with patch("tools._subagent_runner.subprocess.Popen", return_value=fake_proc):
            with patch("tools._subagent_runner._active", {}):
                result = runner.run_subagent(
                    subagent_type="compact",
                    task="task",
                    project_path=tmp_path,
                    handoff_path=handoff_path,
                    timeout=5.0,
                    extra_argv=["--fork-context", str(fc_path)],
                )

        assert not fc_path.exists()
        assert result["status"] == "error"

    def test_fork_context_deleted_after_successful_handoff(self, tmp_path):
        """A terminal success releases the context file after the child has consumed it."""
        state, proc = _make_state(tmp_path, poll_side_effect=[0])
        fc_path = tmp_path / "fork_ctx.json"
        fc_path.write_text('{"version": 2}', encoding="utf-8")
        state.fork_context_path = fc_path
        state.handoff_path.write_text("# Handoff\n\ndone\n", encoding="utf-8")

        result = _poll_until(state, extra_seconds=10)

        assert result["status"] == "ok"
        assert not fc_path.exists()

    def test_fork_context_not_deleted_on_timeout(self, tmp_path):
        """Fork-context file is NOT deleted on timeout (child may be resumed)."""
        from unittest.mock import MagicMock, patch
        import subprocess
        from tools import _subagent_runner as runner

        fc_path = tmp_path / "fork_ctx.json"
        fc_path.write_text('{"version": 1}', encoding="utf-8")
        handoff_path = tmp_path / "handoff.md"

        fake_proc = MagicMock(spec=subprocess.Popen)
        fake_proc.stdout = iter([])
        fake_proc.pid = 99999
        fake_proc.poll.return_value = None  # still running

        with patch("tools._subagent_runner.subprocess.Popen", return_value=fake_proc):
            with patch("tools._subagent_runner._active", {}):
                with patch("time.sleep"):  # don't actually sleep
                    result = runner.run_subagent(
                        subagent_type="compact",
                        task="task",
                        project_path=tmp_path,
                        handoff_path=handoff_path,
                        timeout=0.001,  # immediately times out
                        extra_argv=["--fork-context", str(fc_path)],
                    )

        assert fc_path.exists()
        assert result["status"] == "timeout"


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

    def test_force_kill_cleans_fork_context_and_removes_terminal_state(self, tmp_path, monkeypatch):
        """Forced termination owns terminal cleanup instead of waiting for another poll."""
        fc_path = tmp_path / "fork.json"
        fc_path.write_text('{"version": 2}', encoding="utf-8")
        state, proc = _make_state(tmp_path, poll_side_effect=lambda: None)
        state.fork_context_path = fc_path
        monkeypatch.setattr("tools._subagent_runner.kill_process_tree", lambda _proc: None)
        with _subagent_runner._active_lock:
            _subagent_runner._active[proc.pid] = state

        try:
            _subagent_runner.force_kill_active_subagents()
            assert not fc_path.exists()
            assert not state.task_file.exists()
            assert proc.pid not in _subagent_runner._active
        finally:
            with _subagent_runner._active_lock:
                _subagent_runner._active.pop(proc.pid, None)
