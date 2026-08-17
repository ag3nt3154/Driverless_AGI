"""Tests for tools/subagent_api.py — the unified subagent function."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import session_events as sev
from agent.session_log import SessionLog
from tools.subagent_api import SubagentResult, resume_subagent_by_pid, run_subagent


class TestSubagentResult:
    def test_dataclass_fields(self):
        r = SubagentResult(
            status="ok",
            handoff_text="done",
            handoff_path=Path("/tmp/h.md"),
            session_log_path=Path("/tmp/log"),
            pid=None,
            escalation=None,
        )
        assert r.status == "ok"
        assert r.handoff_text == "done"
        assert r.pid is None

    def test_is_ok_property(self):
        r = SubagentResult(
            status="ok", handoff_text="done",
            handoff_path=Path("/tmp/h.md"),
            session_log_path=Path("/tmp/log"),
            pid=None, escalation=None,
        )
        assert r.is_ok is True

    def test_is_ok_false_for_error(self):
        r = SubagentResult(
            status="error", handoff_text="",
            handoff_path=Path("/tmp/h.md"),
            session_log_path=Path("/tmp/log"),
            pid=None, escalation=None,
        )
        assert r.is_ok is False


class TestRunSubagent:
    def test_preset_loads_config_and_prompt(self, tmp_path):
        """run_subagent(preset=...) loads prompt.md and subagent_config.yaml."""
        preset_dir = tmp_path / ".dagi" / "subagents" / "explore_files"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("You are an explorer.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: [read, grep, find]\nmodel_tier: worker\n"
            "default_handoff_spec: structured report\n"
            "agents_md: [cwd]\n",
            encoding="utf-8",
        )
        handoff_file = tmp_path / ".dagi" / "handoffs" / "explore_files_abc.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("# Handoff\nFound stuff.", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Map the auth module",
                preset="explore_files",
                project_path=tmp_path,
            )

        assert result.status == "ok"
        assert "Found stuff." in result.handoff_text

    def test_custom_prompt_and_tools_without_preset(self, tmp_path):
        """run_subagent() works without a preset when prompt + tools are explicit."""
        handoff_file = tmp_path / ".dagi" / "handoffs" / "custom_abc.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("# Handoff\nCustom result.", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Analyze security",
                prompt="You are a security auditor.",
                tools=["read", "grep"],
                project_path=tmp_path,
            )

        assert result.status == "ok"
        assert "Custom result." in result.handoff_text

    def _make_preset(self, tmp_path: Path, name: str) -> None:
        """Create a minimal local preset so tests don't fall back to _DAGI_ROOT."""
        preset_dir = tmp_path / ".dagi" / "subagents" / name
        preset_dir.mkdir(parents=True, exist_ok=True)
        (preset_dir / "prompt.md").write_text(f"You are a {name} agent.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: [read]\nmodel_tier: worker\n"
            "default_handoff_spec: report\nagents_md: []\n",
            encoding="utf-8",
        )

    def test_error_status_returns_empty_handoff_text(self, tmp_path):
        self._make_preset(tmp_path, "explore_files")
        raw_result = {"status": "error", "message": "exited code 1"}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Fail", preset="explore_files", project_path=tmp_path,
            )

        assert result.status == "error"
        assert result.handoff_text == ""

    def test_timeout_returns_pid(self, tmp_path):
        self._make_preset(tmp_path, "worker")
        raw_result = {"status": "timeout", "pid": 9999}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Slow", preset="worker", project_path=tmp_path,
            )

        assert result.status == "timeout"
        assert result.pid == 9999

    def test_escalated_returns_escalation_text(self, tmp_path):
        self._make_preset(tmp_path, "worker")
        raw_result = {
            "status": "escalated",
            "escalation": "# Escalation\n\n## Question\nWhich lib?",
        }
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Build", preset="worker", project_path=tmp_path,
            )

        assert result.status == "escalated"
        assert "Which lib?" in result.escalation

    def test_requires_preset_or_prompt(self, tmp_path):
        with pytest.raises(ValueError, match="preset.*prompt"):
            run_subagent(task="Do something", project_path=tmp_path)

    def test_explicit_tools_override_preset(self, tmp_path):
        """When both preset and explicit tools are given, explicit wins."""
        preset_dir = tmp_path / ".dagi" / "subagents" / "explore_files"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("Explorer.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: [read, grep, find]\nmodel_tier: worker\n"
            "default_handoff_spec: report\nagents_md: [cwd]\n",
            encoding="utf-8",
        )
        handoff_file = tmp_path / ".dagi" / "handoffs" / "test.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("done", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result) as mock:
            run_subagent(
                task="Do it",
                preset="explore_files",
                tools=["read", "grep", "bash"],
                project_path=tmp_path,
            )

        call_kwargs = mock.call_args.kwargs
        # The --tools arg should contain the explicit override
        extra = call_kwargs.get("extra_argv", [])
        assert "--tools" in extra
        tools_idx = extra.index("--tools")
        assert "read,grep,bash" in extra[tools_idx + 1]

    def test_prompt_forwarded_via_system_prompt_file(self, tmp_path):
        """eff_prompt is written to a temp file and passed as --system-prompt-file."""
        preset_dir = tmp_path / ".dagi" / "subagents" / "explore_files"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("Preset prompt.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: [read]\nmodel_tier: worker\n"
            "default_handoff_spec: report\nagents_md: []\n",
            encoding="utf-8",
        )
        handoff_file = tmp_path / ".dagi" / "handoffs" / "test.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("done", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        captured_prompt_content: list[str] = []

        def capture_and_return(*_args, **kwargs):
            extra = kwargs.get("extra_argv") or []
            if "--system-prompt-file" in extra:
                idx = extra.index("--system-prompt-file")
                captured_prompt_content.append(
                    Path(extra[idx + 1]).read_text(encoding="utf-8")
                )
            return raw_result

        with patch("tools.subagent_api._runner.run_subagent", side_effect=capture_and_return):
            run_subagent(
                task="Do it",
                preset="explore_files",
                prompt="Override prompt text.",
                project_path=tmp_path,
            )

        assert len(captured_prompt_content) == 1, "--system-prompt-file was not passed"
        assert "Override prompt text." in captured_prompt_content[0]

    def test_custom_prompt_forwarded_without_preset(self, tmp_path):
        """When no preset, caller's prompt is forwarded via --system-prompt-file."""
        handoff_file = tmp_path / ".dagi" / "handoffs" / "test.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("done", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        captured: list[str] = []

        def capture_and_return(*_args, **kwargs):
            extra = kwargs.get("extra_argv") or []
            if "--system-prompt-file" in extra:
                idx = extra.index("--system-prompt-file")
                captured.append(Path(extra[idx + 1]).read_text(encoding="utf-8"))
            return raw_result

        with patch("tools.subagent_api._runner.run_subagent", side_effect=capture_and_return):
            run_subagent(
                task="Audit",
                prompt="You are a security auditor.",
                project_path=tmp_path,
            )

        assert len(captured) == 1
        assert "security auditor" in captured[0]


class TestBranchStartLogging:
    """run_subagent() logs branch/start on parent_log before spawning."""

    def _make_open_log(self) -> SessionLog:
        """Return a SessionLog with an open turn and step."""
        log = SessionLog()
        log.append(sev.TURN_START, {"turn": 1})
        log.append(sev.STEP_START, {"turn": 1, "step": 1})
        return log

    @patch("tools.subagent_api._runner.run_subagent")
    def test_branch_start_logged_before_spawn(self, mock_runner):
        """branch/start is appended to parent_log before the subprocess."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = self._make_open_log()
        initial_count = len(log.events)

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                run_subagent(
                    task="test",
                    prompt="do stuff",
                    parent_log=log,
                )

        branch_events = [
            e for e in log.events[initial_count:]
            if e.type == sev.BRANCH_START
        ]
        assert len(branch_events) == 1
        evt = branch_events[0]
        assert evt.data["parent_branch"] == "main"
        assert evt.data["turn"] == 1
        assert evt.data["step"] == 1
        assert evt.branch == "main"

    @patch("tools.subagent_api._runner.run_subagent")
    def test_no_parent_log_no_branch_event(self, mock_runner):
        """When parent_log is None, no branch/start is logged."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    prompt="do stuff",
                )
        assert result.branch_id is None

    @patch("tools.subagent_api._runner.run_subagent")
    def test_branch_id_on_result(self, mock_runner):
        """SubagentResult.branch_id is set when parent_log is provided."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = self._make_open_log()

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    prompt="do stuff",
                    parent_log=log,
                )
        assert result.branch_id is not None
        assert result.branch_id.startswith("custom_")

    @patch("tools.subagent_api._runner.run_subagent")
    def test_branch_id_uses_subagent_type(self, mock_runner, tmp_path):
        """branch_id is prefixed with the subagent type name."""
        handoff_file = tmp_path / ".dagi" / "handoffs" / "explore_files_abc.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("done", encoding="utf-8")
        mock_runner.return_value = {"status": "ok", "handoff": str(handoff_file)}

        preset_dir = tmp_path / ".dagi" / "subagents" / "explore_files"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("Explorer.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: [read]\nmodel_tier: worker\n"
            "default_handoff_spec: report\nagents_md: []\n",
            encoding="utf-8",
        )
        log = self._make_open_log()

        with patch("tools.subagent_api.Path.write_text"):
            result = run_subagent(
                task="test",
                preset="explore_files",
                parent_log=log,
                project_path=tmp_path,
            )
        assert result.branch_id.startswith("explore_files_")

    @patch("tools.subagent_api._runner.run_subagent")
    def test_no_branch_when_no_open_turn(self, mock_runner):
        """No branch/start logged if parent_log has no open turn."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = SessionLog()  # no open turn

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    prompt="do stuff",
                    parent_log=log,
                )
        branch_events = [e for e in log.events if e.type == sev.BRANCH_START]
        assert len(branch_events) == 0
        assert result.branch_id is None


class TestResumeSubagentByPid:
    def test_resume_returns_result(self):
        """resume_subagent_by_pid wraps _runner.resume_subagent and builds result."""
        raw = {"status": "ok", "handoff": "/tmp/h.md"}
        with patch("tools.subagent_api._runner.resume_subagent", return_value=raw), \
             patch("tools.subagent_api._auto_read_handoff", return_value="done"):
            result = resume_subagent_by_pid(9999, 120.0)

        assert result.status == "ok"
        assert result.handoff_text == "done"
        assert result.is_ok is True

    def test_resume_unverified_status(self):
        """resume_subagent_by_pid handles ok_unverified status."""
        raw = {"status": "ok_unverified", "handoff": "/tmp/h.md"}
        with patch("tools.subagent_api._runner.resume_subagent", return_value=raw), \
             patch("tools.subagent_api._auto_read_handoff", return_value="scraped"):
            result = resume_subagent_by_pid(9999, 120.0)

        assert result.status == "ok_unverified"
        assert result.handoff_text == "scraped"
        assert result.is_ok is True

    def test_resume_error_status(self):
        """resume_subagent_by_pid handles error status without reading handoff."""
        raw = {"status": "error", "message": "exited with code 1", "pid": 9999}
        with patch("tools.subagent_api._runner.resume_subagent", return_value=raw):
            result = resume_subagent_by_pid(9999, 120.0)

        assert result.status == "error"
        assert result.handoff_text == ""
        assert result.is_ok is False
        assert result.pid == 9999

    def test_resume_escalation_status(self):
        """resume_subagent_by_pid preserves escalation field."""
        raw = {
            "status": "escalated",
            "handoff": "/tmp/h.md",
            "escalation": "Needs review.",
            "pid": 9999,
        }
        with patch("tools.subagent_api._runner.resume_subagent", return_value=raw):
            result = resume_subagent_by_pid(9999, 120.0)

        assert result.status == "escalated"
        assert result.escalation == "Needs review."
        assert result.pid == 9999
