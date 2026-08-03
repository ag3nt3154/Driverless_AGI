"""Tests for tools/subagent_api.py — the unified subagent function."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.subagent_api import SubagentResult, run_subagent


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

    def test_error_status_returns_empty_handoff_text(self, tmp_path):
        raw_result = {"status": "error", "message": "exited code 1"}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Fail", preset="explore_files", project_path=tmp_path,
            )

        assert result.status == "error"
        assert result.handoff_text == ""

    def test_timeout_returns_pid(self, tmp_path):
        raw_result = {"status": "timeout", "pid": 9999}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Slow", preset="worker", project_path=tmp_path,
            )

        assert result.status == "timeout"
        assert result.pid == 9999

    def test_escalated_returns_escalation_text(self, tmp_path):
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
