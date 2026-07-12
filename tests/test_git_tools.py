"""tests/test_git_tools.py — Unit tests for tools/git.py."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.git import (
    GitAddTool,
    GitBranchTool,
    GitCheckoutTool,
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitResetTool,
    GitStatusTool,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo on 'main' with one commit, plus a checked-out 'dagi/test-task' branch."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "dagi/test-task"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


class TestGitStatusTool:
    def test_reports_branch_and_clean_state(self, repo: Path):
        result = GitStatusTool(cwd=repo).run()
        assert "Branch: dagi/test-task" in result
        assert "Status: clean" in result

    def test_reports_dirty_state_with_changed_files(self, repo: Path):
        (repo / "new.txt").write_text("hi\n", encoding="utf-8")
        result = GitStatusTool(cwd=repo).run()
        assert "Status: dirty" in result
        assert "new.txt" in result


class TestGitDiffTool:
    def test_no_changes(self, repo: Path):
        assert GitDiffTool(cwd=repo).run() == "No changes."

    def test_shows_unstaged_diff(self, repo: Path):
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        result = GitDiffTool(cwd=repo).run()
        assert "README.md" in result
        assert "changed" in result

    def test_staged_true_shows_only_staged_diff(self, repo: Path):
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        assert GitDiffTool(cwd=repo).run(staged=True) == "No changes."
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        result = GitDiffTool(cwd=repo).run(staged=True)
        assert "README.md" in result


class TestGitLogTool:
    def test_shows_recent_commits(self, repo: Path):
        result = GitLogTool(cwd=repo).run()
        assert "init" in result

    def test_count_limits_output_lines(self, repo: Path):
        for i in range(3):
            (repo / f"f{i}.txt").write_text("x\n", encoding="utf-8")
            subprocess.run(["git", "add", f"f{i}.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", f"commit {i}"], cwd=repo, check=True, capture_output=True)
        result = GitLogTool(cwd=repo).run(count=2)
        assert len(result.splitlines()) == 2


class TestGitBranchTool:
    def test_lists_branches_with_current_marked(self, repo: Path):
        result = GitBranchTool(cwd=repo).run()
        assert "* dagi/test-task" in result
        assert "main" in result

    def test_create_adds_branch_without_switching(self, repo: Path):
        result = GitBranchTool(cwd=repo).run(create="dagi/other-task")
        assert "dagi/other-task" in result
        current = subprocess.run(
            ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert current == "dagi/test-task"  # unchanged — create doesn't switch


class TestGitCheckoutTool:
    def test_switches_to_existing_branch(self, repo: Path):
        result = GitCheckoutTool(cwd=repo).run(branch="main")
        assert "main" in result
        current = subprocess.run(
            ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert current == "main"

    def test_create_true_makes_new_branch(self, repo: Path):
        GitCheckoutTool(cwd=repo).run(branch="dagi/brand-new", create=True)
        current = subprocess.run(
            ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert current == "dagi/brand-new"

    def test_unrestricted_even_to_main(self, repo: Path):
        """git_checkout has no dagi/* guard — it can switch anywhere, any time."""
        result = GitCheckoutTool(cwd=repo).run(branch="main")
        assert "Checkout failed" not in result


class TestGitAddTool:
    def test_stages_named_paths_on_dagi_branch(self, repo: Path):
        (repo / "new.txt").write_text("hi\n", encoding="utf-8")
        result = GitAddTool(cwd=repo).run(paths=["new.txt"])
        assert "new.txt" in result

    def test_refused_on_main(self, repo: Path):
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        (repo / "new.txt").write_text("hi\n", encoding="utf-8")
        result = GitAddTool(cwd=repo).run(paths=["new.txt"])
        assert "Error" in result
        assert "dagi/" in result


class TestGitCommitTool:
    def test_commits_staged_changes(self, repo: Path):
        (repo / "new.txt").write_text("hi\n", encoding="utf-8")
        GitAddTool(cwd=repo).run(paths=["new.txt"])
        result = GitCommitTool(cwd=repo).run(message="add new.txt")
        assert "Committed:" in result
        assert "new.txt" in result

    def test_errors_when_nothing_staged(self, repo: Path):
        result = GitCommitTool(cwd=repo).run(message="empty commit attempt")
        assert "Nothing staged" in result

    def test_no_longer_auto_stages_unstaged_changes(self, repo: Path):
        """Regression guard: git_commit must NOT run `add -A` anymore."""
        (repo / "untracked.txt").write_text("hi\n", encoding="utf-8")
        result = GitCommitTool(cwd=repo).run(message="should not commit untracked")
        assert "Nothing staged" in result

    def test_refused_on_main(self, repo: Path):
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        result = GitCommitTool(cwd=repo).run(message="on main")
        assert "Error" in result
        assert "dagi/" in result


class TestGitResetTool:
    def test_mixed_reset_keeps_working_tree_changes(self, repo: Path):
        (repo / "README.md").write_text("v2\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "v2"], cwd=repo, check=True, capture_output=True)

        result = GitResetTool(cwd=repo).run(ref="HEAD~1", mode="mixed")
        assert "Reset (mixed)" in result
        assert (repo / "README.md").read_text(encoding="utf-8") == "v2\n"  # working tree unchanged

    def test_hard_reset_discards_changes(self, repo: Path):
        (repo / "README.md").write_text("v2\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "v2"], cwd=repo, check=True, capture_output=True)

        GitResetTool(cwd=repo).run(ref="HEAD~1", mode="hard")
        assert (repo / "README.md").read_text(encoding="utf-8") == "init\n"

    def test_soft_reset_keeps_changes_staged(self, repo: Path):
        (repo / "README.md").write_text("v2\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "v2"], cwd=repo, check=True, capture_output=True)

        result = GitResetTool(cwd=repo).run(ref="HEAD~1", mode="soft")
        assert "Reset (soft)" in result
        assert (repo / "README.md").read_text(encoding="utf-8") == "v2\n"  # content differs from HEAD~1

        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert "README.md" in staged.splitlines()

        unstaged = subprocess.run(
            ["git", "diff", "--name-only"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert "README.md" not in unstaged.splitlines()

    def test_clean_removes_untracked_files(self, repo: Path):
        (repo / "untracked.txt").write_text("scratch\n", encoding="utf-8")
        assert (repo / "untracked.txt").exists()

        GitResetTool(cwd=repo).run(ref="HEAD", mode="mixed", clean=True)

        assert not (repo / "untracked.txt").exists()

    def test_invalid_mode_rejected(self, repo: Path):
        result = GitResetTool(cwd=repo).run(mode="bogus")
        assert "Error" in result

    def test_refused_on_main(self, repo: Path):
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        result = GitResetTool(cwd=repo).run()
        assert "Error" in result
        assert "dagi/" in result


class TestGitRollbackRemoved:
    def test_git_rollback_tool_class_no_longer_exists(self):
        import tools.git as git_module
        assert not hasattr(git_module, "GitRollbackTool")
