"""tests/test_plan_mode_branch.py — Auto-branch creation on entering plan mode."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.loop import AgentConfig, AgentLoop


def _make_loop(project_path: Path) -> AgentLoop:
    """Create an AgentLoop with heavy dependencies mocked out, rooted at project_path."""
    config = AgentConfig(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        project_path=project_path,
    )

    fake_registry = MagicMock()
    fake_registry.get_openai_tools_list.return_value = []
    fake_registry.list_tools.return_value = []

    fake_tracker = MagicMock()
    fake_tracker.record_system = MagicMock()
    fake_tracker.record_user = MagicMock()
    fake_tracker.record_assistant = MagicMock()

    with (
        patch("agent.loop.SessionTracker", return_value=fake_tracker),
        patch("openai.OpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        loop = AgentLoop(config=config, _registry=fake_registry, _tracker=fake_tracker)

    loop.tracker = fake_tracker
    loop.registry = fake_registry
    return loop


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


class TestEnterPlanModeAutoBranch:
    def test_requires_task_summary(self, tmp_path: Path):
        loop = _make_loop(tmp_path)
        result = loop._handle_enter_plan_mode({"mode": "interactive"})
        assert "task_summary is required" in result

    def test_creates_branch_in_git_repo(self, git_repo: Path):
        loop = _make_loop(git_repo)
        loop._handle_enter_plan_mode({"mode": "interactive", "task_summary": "Fix Git Tools"})

        current = subprocess.run(
            ["git", "branch", "--show-current"], cwd=git_repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert current.startswith("dagi/fix-git-tools_plan_")

    def test_skips_silently_without_git_repo(self, tmp_path: Path):
        loop = _make_loop(tmp_path)
        result = loop._handle_enter_plan_mode({"mode": "interactive", "task_summary": "Fix Git Tools"})

        assert "no git repository detected" in result.lower()
        # Plan mode still activated normally
        assert "Plan mode activated" in result

    def test_plan_title_seeded_with_task_summary(self, git_repo: Path):
        loop = _make_loop(git_repo)
        loop._handle_enter_plan_mode({"mode": "interactive", "task_summary": "Fix Git Tools"})
        plan_file = Path(loop.config.plan_file)
        assert "# Plan: Fix Git Tools" in plan_file.read_text(encoding="utf-8")
