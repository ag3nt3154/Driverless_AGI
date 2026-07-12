"""tests/test_git_branch.py — Unit tests for agent/_git_branch.py."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent._git_branch import build_branch_name, create_task_branch, is_git_repo, slugify


class TestSlugify:
    def test_lowercases_and_hyphenates(self):
        assert slugify("Fix Git Tools") == "fix-git-tools"

    def test_strips_punctuation(self):
        assert slugify("Fix Git Tools!! (urgent)") == "fix-git-tools-urgent"

    def test_collapses_and_trims_hyphens(self):
        assert slugify("  --Fix   Git--Tools--  ") == "fix-git-tools"

    def test_truncates_to_max_len(self):
        long_text = "a" * 100
        result = slugify(long_text, max_len=10)
        assert result == "a" * 10

    def test_truncation_does_not_leave_trailing_hyphen(self):
        # slug before truncation: "fix-git-tools-for-real" -> cut at 15 chars lands mid-word
        result = slugify("fix git tools for real", max_len=14)
        assert not result.endswith("-")

    def test_empty_input_falls_back_to_task(self):
        assert slugify("") == "task"

    def test_punctuation_only_input_falls_back_to_task(self):
        assert slugify("!!!???") == "task"


class TestBuildBranchName:
    def test_builds_expected_pattern(self):
        name = build_branch_name("Fix Git Tools", "plan_20260712_153045")
        assert name == "dagi/fix-git-tools_plan_20260712_153045"


class TestIsGitRepo:
    def test_true_for_initialized_repo(self, tmp_path: Path):
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
        assert is_git_repo(tmp_path) is True

    def test_false_for_non_repo_dir(self, tmp_path: Path):
        assert is_git_repo(tmp_path) is False


class TestCreateTaskBranch:
    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("init\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True
        )
        return tmp_path

    def test_creates_and_checks_out_branch(self, repo: Path):
        branch_name = create_task_branch(repo, "Fix Git Tools", "plan_20260712_153045")
        assert branch_name == "dagi/fix-git-tools_plan_20260712_153045"

        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == branch_name

    def test_returns_none_when_not_a_git_repo(self, tmp_path: Path):
        assert create_task_branch(tmp_path, "Fix Git Tools", "plan_20260712_153045") is None

    def test_raises_on_branch_creation_failure(self, repo: Path):
        # Create the branch once, then try again — second call collides with existing branch.
        create_task_branch(repo, "Fix Git Tools", "plan_20260712_153045")
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        with pytest.raises(RuntimeError):
            create_task_branch(repo, "Fix Git Tools", "plan_20260712_153045")
