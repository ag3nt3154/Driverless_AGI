"""tests/test_spawn_subagent_tool_unverified.py — ok_unverified handoff coverage.

Split out of test_spawn_subagent_tool.py (which was breaching the 500-line
file cap) to keep both files comfortably under the limit. Covers the
ok_unverified warning-banner behaviour introduced across SpawnSubagentTool
and every other tool that branches on run_subagent()'s status: cli_subagent,
extend_timeout, explore_files, and web_research.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.spawn_subagent import SpawnSubagentTool, _FALLBACK_PARAMETERS


# ---------------------------------------------------------------------------
# Helpers / fixtures (mirrors test_spawn_subagent_tool.py)
# ---------------------------------------------------------------------------

WORKER_SCHEMA = {
    "type": "object",
    "properties": {
        "subtask_name": {"type": "string", "description": "Name of the subtask."},
        "custom_instructions": {"type": "string", "description": "Extra instructions."},
    },
    "required": ["subtask_name"],
}


def _make_config(project_path: Path, plan_file: Path | None = None) -> MagicMock:
    cfg = MagicMock()
    cfg.project_path = project_path
    cfg.plan_file = plan_file
    cfg.active_plan_file = None
    return cfg


def _make_tool(type_name: str, config, parameters: dict | None = None) -> SpawnSubagentTool:
    """Create a SpawnSubagentTool with _parameters pre-set (bypasses file I/O)."""
    with patch.object(SpawnSubagentTool, "_load_parameters", return_value=parameters or _FALLBACK_PARAMETERS):
        tool = SpawnSubagentTool(
            type_name=type_name,
            description=f"Test {type_name} tool",
            config=config,
        )
    return tool


# ---------------------------------------------------------------------------
# SpawnSubagentTool.run() — ok_unverified
# ---------------------------------------------------------------------------

class TestSpawnSubagentRunOkUnverified:
    def test_run_ok_unverified_includes_handoff_content_and_warning(self, tmp_path):
        """run() must inline the handoff content AND prepend an unmistakable
        warning banner when the subagent never called write_handoff."""
        handoff_file = tmp_path / "worker_abc123.md"
        handoff_file.write_text(
            "# Closing message\n\nI finished the login endpoint.",
            encoding="utf-8",
        )
        config = _make_config(tmp_path)
        tool = _make_tool("worker", config, WORKER_SCHEMA)
        unverified_result = {"status": "ok_unverified", "handoff": str(handoff_file)}

        with patch("tools._subagent_runner.run_subagent", return_value=unverified_result):
            result = tool.run(subtask_name="Do the thing")

        assert "I finished the login endpoint." in result
        assert "write_handoff" in result.lower()
        assert "unverified" in result.lower()

    def test_run_ok_status_has_no_warning_banner(self, tmp_path):
        """Regression: the 'ok' path must remain unchanged — no warning banner."""
        handoff_file = tmp_path / "worker_def456.md"
        handoff_file.write_text("# Handoff\n\nDone.", encoding="utf-8")
        config = _make_config(tmp_path)
        tool = _make_tool("worker", config, WORKER_SCHEMA)
        ok_result = {"status": "ok", "handoff": str(handoff_file)}

        with patch("tools._subagent_runner.run_subagent", return_value=ok_result):
            result = tool.run(subtask_name="Do the thing")

        assert "unverified" not in result.lower()
        assert "write_handoff" not in result.lower()

    def test_run_ok_unverified_reports_unreadable_handoff_without_raising(self, tmp_path):
        """If the handoff file can't be read for an ok_unverified result, run()
        must still degrade gracefully, keeping the warning banner present."""
        missing_path = tmp_path / "does_not_exist.md"
        config = _make_config(tmp_path)
        tool = _make_tool("worker", config, WORKER_SCHEMA)
        unverified_result = {"status": "ok_unverified", "handoff": str(missing_path)}

        with patch("tools._subagent_runner.run_subagent", return_value=unverified_result):
            result = tool.run(subtask_name="Do the thing")

        assert str(missing_path) in result
        assert "could not read handoff" in result.lower()
        assert "unverified" in result.lower()
        assert "write_handoff" in result.lower()


# ---------------------------------------------------------------------------
# SpawnCliSubagentTool.run() — ok / ok_unverified
# ---------------------------------------------------------------------------

class TestCliSubagentRunStatus:
    def _make_tool(self, tmp_path):
        from tools.cli_subagent import SpawnCliSubagentTool

        return SpawnCliSubagentTool(project_path=tmp_path)

    def test_run_ok_status_has_no_warning_banner(self, tmp_path):
        tool = self._make_tool(tmp_path)
        ok_result = {"status": "ok", "handoff": str(tmp_path / "custom_abc.md")}

        with patch("tools._subagent_runner.run_subagent", return_value=ok_result):
            result = tool.run(system_prompt="You are a helper.", task="Do a thing")

        assert "Handoff written to" in result
        assert "unverified" not in result.lower()
        assert "write_handoff" not in result.lower()

    def test_run_ok_unverified_includes_warning_banner(self, tmp_path):
        tool = self._make_tool(tmp_path)
        unverified_result = {
            "status": "ok_unverified",
            "handoff": str(tmp_path / "custom_def.md"),
        }

        with patch("tools._subagent_runner.run_subagent", return_value=unverified_result):
            result = tool.run(system_prompt="You are a helper.", task="Do a thing")

        assert "Handoff written to" in result
        assert "unverified" in result.lower()
        assert "write_handoff" in result.lower()


# ---------------------------------------------------------------------------
# ExtendSubagentTimeoutTool.run() — ok / ok_unverified
# ---------------------------------------------------------------------------

class TestExtendTimeoutRunStatus:
    def test_run_ok_status_has_no_warning_banner(self, tmp_path):
        from tools.extend_timeout import ExtendSubagentTimeoutTool

        handoff_file = tmp_path / "worker_abc.md"
        handoff_file.write_text("# Handoff\n\nDone.", encoding="utf-8")
        tool = ExtendSubagentTimeoutTool()
        ok_result = {"status": "ok", "handoff": str(handoff_file)}

        with patch("tools._subagent_runner.resume_subagent", return_value=ok_result):
            result = tool.run(pid=12345)

        assert "Done." in result
        assert "unverified" not in result.lower()
        assert "write_handoff" not in result.lower()

    def test_run_ok_unverified_includes_warning_banner(self, tmp_path):
        from tools.extend_timeout import ExtendSubagentTimeoutTool

        handoff_file = tmp_path / "worker_def.md"
        handoff_file.write_text("# Closing message\n\nScraped text.", encoding="utf-8")
        tool = ExtendSubagentTimeoutTool()
        unverified_result = {"status": "ok_unverified", "handoff": str(handoff_file)}

        with patch("tools._subagent_runner.resume_subagent", return_value=unverified_result):
            result = tool.run(pid=12345)

        assert "Scraped text." in result
        assert "unverified" in result.lower()
        assert "write_handoff" in result.lower()


# ---------------------------------------------------------------------------
# ExploreFilesTool.run() — ok / ok_unverified
# ---------------------------------------------------------------------------

class TestExploreFilesRunStatus:
    def _make_tool(self, tmp_path):
        from tools.explore_files import ExploreFilesTool

        config = _make_config(tmp_path)
        return ExploreFilesTool(config=config)

    def test_run_ok_status_has_no_warning_banner(self, tmp_path):
        handoff_dir = tmp_path / ".dagi" / "handoffs"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "explore_files_abc.md"
        handoff_file.write_text("# Exploration report\n\nFound it.", encoding="utf-8")
        tool = self._make_tool(tmp_path)
        ok_result = {"status": "ok", "handoff": str(handoff_file)}

        with patch("tools._subagent_runner.run_subagent", return_value=ok_result):
            result = tool.run(task="Find the thing")

        assert "Found it." in result
        assert "unverified" not in result.lower()
        assert "write_handoff" not in result.lower()

    def test_run_ok_unverified_includes_warning_banner(self, tmp_path):
        handoff_dir = tmp_path / ".dagi" / "handoffs"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "explore_files_def.md"
        handoff_file.write_text("# Closing message\n\nScraped exploration notes.", encoding="utf-8")
        tool = self._make_tool(tmp_path)
        unverified_result = {"status": "ok_unverified", "handoff": str(handoff_file)}

        with patch("tools._subagent_runner.run_subagent", return_value=unverified_result):
            result = tool.run(task="Find the thing")

        assert "Scraped exploration notes." in result
        assert "unverified" in result.lower()
        assert "write_handoff" in result.lower()


# ---------------------------------------------------------------------------
# WebResearchTool.run() — ok / ok_unverified
# ---------------------------------------------------------------------------

class TestWebResearchRunStatus:
    def _make_tool(self, tmp_path):
        from tools.web_research import WebResearchTool

        config = _make_config(tmp_path)
        return WebResearchTool(config=config)

    def test_run_ok_status_has_no_warning_banner(self, tmp_path):
        handoff_dir = tmp_path / ".dagi" / "handoffs"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "web_research_abc.md"
        handoff_file.write_text("# Research report\n\nSources found.", encoding="utf-8")
        tool = self._make_tool(tmp_path)
        ok_result = {"status": "ok", "handoff": str(handoff_file)}

        with patch("tools._subagent_runner.run_subagent", return_value=ok_result):
            result = tool.run(task="Research the thing")

        assert "Sources found." in result
        assert "unverified" not in result.lower()
        assert "write_handoff" not in result.lower()

    def test_run_ok_unverified_includes_warning_banner(self, tmp_path):
        handoff_dir = tmp_path / ".dagi" / "handoffs"
        handoff_dir.mkdir(parents=True)
        handoff_file = handoff_dir / "web_research_def.md"
        handoff_file.write_text("# Closing message\n\nScraped research notes.", encoding="utf-8")
        tool = self._make_tool(tmp_path)
        unverified_result = {"status": "ok_unverified", "handoff": str(handoff_file)}

        with patch("tools._subagent_runner.run_subagent", return_value=unverified_result):
            result = tool.run(task="Research the thing")

        assert "Scraped research notes." in result
        assert "unverified" in result.lower()
        assert "write_handoff" in result.lower()
