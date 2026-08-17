"""Integration: subagent spawn logs branch/start on parent SessionLog."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agent import session_events as sev
from agent.session_log import SessionLog


def _make_open_log() -> SessionLog:
    """Return a SessionLog with turn 1 and step 1 open."""
    log = SessionLog()
    log.append(sev.TURN_START, {"turn": 1})
    log.append(sev.STEP_START, {"turn": 1, "step": 1})
    return log


def _make_preset(tmp_path: Path, name: str) -> None:
    """Create a minimal local preset so tests don't fall back to _DAGI_ROOT."""
    preset_dir = tmp_path / ".dagi" / "subagents" / name
    preset_dir.mkdir(parents=True)
    (preset_dir / "prompt.md").write_text(f"You are a {name} agent.", encoding="utf-8")
    (preset_dir / "subagent_config.yaml").write_text(
        "tools: [read]\nmodel_tier: worker\n"
        "default_handoff_spec: report\nagents_md: []\n",
        encoding="utf-8",
    )


class TestBranchStartViaRunSubagent:
    """run_subagent() integration: branch/start logged before subprocess spawns."""

    def test_branch_start_logged_on_spawn(self, tmp_path):
        """run_subagent() appends branch/start to parent_log before spawning."""
        _make_preset(tmp_path, "explore_files")
        log = _make_open_log()
        initial_count = len(log.events)

        raw_result = {"status": "ok", "handoff": str(tmp_path / "fake.md")}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            from tools.subagent_api import run_subagent
            result = run_subagent(
                task="find API routes",
                preset="explore_files",
                project_path=tmp_path,
                parent_log=log,
            )

        branch_events = [
            e for e in log.events[initial_count:]
            if e.type == sev.BRANCH_START
        ]
        assert len(branch_events) == 1, "exactly one branch/start must be logged"
        evt = branch_events[0]
        assert evt.data["parent_branch"] == "main"
        assert evt.data["turn"] == 1
        assert evt.data["step"] == 1
        assert evt.data["branch"].startswith("explore_files_")
        assert result.branch_id == evt.data["branch"]

    def test_branch_registered_in_log_branches(self, tmp_path):
        """After spawn, log.branches contains the new branch entry."""
        _make_preset(tmp_path, "explore_files")
        log = _make_open_log()

        raw_result = {"status": "ok", "handoff": str(tmp_path / "fake.md")}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            from tools.subagent_api import run_subagent
            result = run_subagent(
                task="explore the codebase",
                preset="explore_files",
                project_path=tmp_path,
                parent_log=log,
            )

        assert result.branch_id is not None
        assert result.branch_id in log.branches
        parent_branch, turn, step = log.branches[result.branch_id]
        assert parent_branch == "main"
        assert turn == 1
        assert step == 1

    def test_no_parent_log_no_branch_event(self, tmp_path):
        """When parent_log=None, no branch/start is logged (backward compatibility)."""
        _make_preset(tmp_path, "explore_files")

        raw_result = {"status": "ok", "handoff": str(tmp_path / "fake.md")}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            from tools.subagent_api import run_subagent
            result = run_subagent(
                task="explore quietly",
                preset="explore_files",
                project_path=tmp_path,
                parent_log=None,
            )

        assert result.branch_id is None


class TestBranchStartViaDiscoveredTool:
    """End-to-end: _discover_subagent_tools() → tool.run() → branch/start on log."""

    def test_subagent_tool_run_logs_branch_start(self, tmp_path):
        """ExploreFilesTool.run() forwards session_log; branch/start appears in log."""
        from unittest.mock import MagicMock
        from agent.subagent_tools import _discover_subagent_tools

        log = _make_open_log()
        config = MagicMock()
        config.project_path = tmp_path

        tools = _discover_subagent_tools(
            cwd=tmp_path,
            config=config,
            callbacks=None,
            tracker=None,
            session_log=log,
        )

        explore_tool = next(
            (t for t in tools if t.name == "explore_files"), None
        )
        if explore_tool is None:
            pytest.skip("explore_files tool not discovered — check DAGI_ROOT scan")

        initial_count = len(log.events)
        raw_result = {"status": "ok", "handoff": str(tmp_path / "fake.md")}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            explore_tool.run(task="find API routes")

        branch_events = [
            e for e in log.events[initial_count:]
            if e.type == sev.BRANCH_START
        ]
        assert len(branch_events) == 1, "exactly one branch/start must reach the log"
        evt = branch_events[0]
        assert evt.data["parent_branch"] == "main"
        assert evt.data["turn"] == 1
        assert evt.data["step"] == 1
        assert evt.data["branch"].startswith("explore_files_")

    def test_branch_in_log_branches_after_tool_run(self, tmp_path):
        """log.branches is populated after ExploreFilesTool.run()."""
        from unittest.mock import MagicMock
        from agent.subagent_tools import _discover_subagent_tools

        log = _make_open_log()
        config = MagicMock()
        config.project_path = tmp_path

        tools = _discover_subagent_tools(
            cwd=tmp_path,
            config=config,
            callbacks=None,
            tracker=None,
            session_log=log,
        )

        explore_tool = next(
            (t for t in tools if t.name == "explore_files"), None
        )
        if explore_tool is None:
            pytest.skip("explore_files tool not discovered — check DAGI_ROOT scan")

        raw_result = {"status": "ok", "handoff": str(tmp_path / "fake.md")}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            explore_tool.run(task="check auth module")

        assert len(log.branches) == 1
        branch_id = next(iter(log.branches))
        parent_branch, turn, step = log.branches[branch_id]
        assert parent_branch == "main"
        assert turn == 1
        assert step == 1


class TestBranchStartDirectAppend:
    """Direct SessionLog.append(branch/start) works as the integration spec describes."""

    def test_branch_registered_in_log(self):
        """Appending branch/start directly registers it in log.branches."""
        log = SessionLog()
        log.append(sev.TURN_START, {"turn": 1})
        log.append(sev.STEP_START, {"turn": 1, "step": 1})

        log.append(sev.BRANCH_START, {
            "branch": "explore_files_test123",
            "parent_branch": "main",
            "turn": 1,
            "step": 1,
        })

        assert "explore_files_test123" in log.branches
        parent_branch, turn, step = log.branches["explore_files_test123"]
        assert parent_branch == "main"
        assert turn == 1
        assert step == 1
