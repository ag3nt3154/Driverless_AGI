# DAGI Git Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give DAGI a basic everyday git toolkit (status/diff/log/branch/checkout/add/commit/reset) that operates freely, auto-branches every plan-mode task onto its own `dagi/<slug>_<plan_id>` branch, and blocks mutating operations (add/commit/reset) from ever touching anything but a `dagi/*` branch — while merge, force-push, and branch delete/rename remain entirely absent from DAGI's tool surface (user-only).

**Architecture:** `tools/git.py` gets five new tools (`git_diff`, `git_log`, `git_branch`, `git_checkout`, `git_add`) plus a rewritten `git_commit` (explicit staging, no `add -A`) and a new `git_reset` that replaces the removed `git_rollback`. A new isolated module, `agent/_git_branch.py`, owns branch-name slugification and creation so it's unit-testable without constructing a full `AgentLoop`. `agent/loop.py._handle_enter_plan_mode` calls into that module as a side effect of entering plan mode; `tools/plan_mode.py`'s `EnterPlanModeTool` gains a required `task_summary` field to supply the slug. The `plan-work-review` skill doc is updated to call the new commit step per subtask and to report the branch + merge reminder at the end.

**Tech Stack:** Python 3.11+/3.14, `subprocess` (git CLI wrapping — matches existing `tools/git.py` pattern), `pytest` (existing test suite conventions in `tests/`).

**Reference spec:** `docs/superpowers/specs/2026-07-12-dagi-git-workflow-design.md`

---

### Task 1: Branch-naming helper module

**Files:**
- Create: `agent/_git_branch.py`
- Test: `tests/test_git_branch.py`

- [ ] **Step 1: Write the failing tests**

```python
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
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("init\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
        return tmp_path

    def test_creates_and_checks_out_branch(self, repo: Path):
        branch_name = create_task_branch(repo, "Fix Git Tools", "plan_20260712_153045")
        assert branch_name == "dagi/fix-git-tools_plan_20260712_153045"

        result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, check=True
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_git_branch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent._git_branch'`

- [ ] **Step 3: Write the implementation**

```python
"""agent/_git_branch.py — Auto-branch creation for plan-mode tasks.

Isolated helper functions used by AgentLoop._handle_enter_plan_mode() to create
and check out a dedicated `dagi/<slug>_<plan_id>` branch for every plan-mode
task, so plan-mode work never lands directly on main/master. Kept separate
from agent/loop.py so it can be unit-tested without constructing a full
AgentLoop.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_BRANCH_PREFIX = "dagi/"
_MAX_SLUG_LEN = 40


def slugify(text: str, max_len: int = _MAX_SLUG_LEN) -> str:
    """Lowercase, hyphenate, strip non-alphanumerics, collapse/trim hyphens, truncate.

    Falls back to "task" if the input has no alphanumeric characters at all.
    """
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        return "task"
    return text[:max_len].rstrip("-") or "task"


def build_branch_name(task_summary: str, plan_id: str) -> str:
    """Return 'dagi/{slug}_{plan_id}'. plan_id is e.g. 'plan_20260712_153045'."""
    return f"{_BRANCH_PREFIX}{slugify(task_summary)}_{plan_id}"


def is_git_repo(cwd: Path) -> bool:
    """Return True if cwd is inside a git working tree. False if not a repo or git is missing."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            cwd=str(cwd),
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def create_task_branch(cwd: Path, task_summary: str, plan_id: str) -> str | None:
    """Create and check out a new dagi/<slug>_<plan_id> branch from the current HEAD.

    Returns the branch name on success, or None if cwd is not a git repository
    (skip silently — plan mode still proceeds without a git workflow).
    Raises RuntimeError if it IS a repo but branch creation fails for another
    reason (e.g. a branch with that name already exists).
    """
    if not is_git_repo(cwd):
        return None

    branch_name = build_branch_name(task_summary, plan_id)
    result = subprocess.run(
        ["git", "checkout", "-b", branch_name],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create branch '{branch_name}': "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return branch_name
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_git_branch.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/_git_branch.py tests/test_git_branch.py
git commit -m "feat: add branch-naming helper for plan-mode auto-branching"
```

---

### Task 2: Expand `tools/git.py` — new tools, rewritten commit, new reset

**Files:**
- Modify: `tools/git.py` (full rewrite)
- Test: `tests/test_git_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_git_tools.py -v`
Expected: FAIL with `ImportError: cannot import name 'GitDiffTool' from 'tools.git'`

- [ ] **Step 3: Write the implementation**

```python
"""tools/git.py — Basic git tools for DAGI.

DAGI can freely use status/diff/log/branch/checkout at any time. Mutating
operations (add, commit, reset) are restricted to branches under the
`dagi/` prefix — the branches auto-created by agent/_git_branch.py when
entering plan mode. Anything outside that lane (main, master, some other
pre-existing branch) is refused.

Note: this guard is enforced only at this tool layer. BashTool remains
registered unrestricted alongside these tools and can run any git command
directly (including on main). See docs/superpowers/specs/2026-07-12-dagi-git-workflow-design.md
"Accepted Limitations" for the full explanation — these tools are a paved
path, not a security boundary.

Operations intentionally NOT exposed to DAGI at all: merge, force-push,
branch delete/rename. Those remain user-only.
"""
import subprocess
from pathlib import Path

from agent.base_tool import BaseTool

_DAGI_BRANCH_PREFIX = "dagi/"
_VALID_RESET_MODES = {"soft", "mixed", "hard"}


def _run_git(args: list[str], cwd: Path) -> tuple[str, str, int]:
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def _current_branch(cwd: Path) -> str:
    out, _, _ = _run_git(["branch", "--show-current"], cwd)
    return out or "(detached HEAD)"


def _dagi_branch_guard(cwd: Path) -> str | None:
    branch = _current_branch(cwd)
    if not branch.startswith(_DAGI_BRANCH_PREFIX):
        return (
            f"Error: this tool only operates on '{_DAGI_BRANCH_PREFIX}*' branches. "
            f"Currently on '{branch}'. DAGI creates these branches automatically "
            f"when entering plan mode."
        )
    return None


class GitStatusTool(BaseTool):
    name = "git_status"
    description = (
        "Return the current git status: branch name, clean/dirty state, "
        "list of changed files, and the last 5 commits. Safe on any branch."
    )
    _parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, **_kwargs) -> str:
        branch = _current_branch(self.cwd)
        porcelain, _, _ = _run_git(["status", "--porcelain"], self.cwd)
        log, _, _ = _run_git(["log", "--oneline", "-5"], self.cwd)

        changed = [line[3:] for line in porcelain.splitlines() if line.strip()]
        is_clean = not changed

        lines = [f"Branch: {branch}", f"Status: {'clean' if is_clean else 'dirty'}"]
        if changed:
            lines.append("Changed files:")
            lines.extend(f"  {f}" for f in changed)
        if log:
            lines.append("Recent commits:")
            lines.extend(f"  {c}" for c in log.splitlines())
        return "\n".join(lines)


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = (
        "Show the diff of unstaged changes (or staged changes if staged=true), "
        "optionally scoped to a single path. Safe on any branch."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "staged": {"type": "boolean", "description": "Show staged (cached) diff instead of the working tree diff. Default: false."},
            "path": {"type": "string", "description": "Limit the diff to this file or directory."},
        },
        "required": [],
    }

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, staged: bool = False, path: str | None = None, **_kwargs) -> str:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args.extend(["--", path])
        out, err, rc = _run_git(args, self.cwd)
        if rc != 0:
            return f"git diff failed:\n{err or out}"
        return out or "No changes."


class GitLogTool(BaseTool):
    name = "git_log"
    description = (
        "Show recent commit history (oneline format), optionally scoped to a "
        "single path. Safe on any branch."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "description": "Number of commits to show. Default: 10."},
            "path": {"type": "string", "description": "Limit history to this file or directory."},
        },
        "required": [],
    }

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, count: int = 10, path: str | None = None, **_kwargs) -> str:
        args = ["log", "--oneline", f"-{max(1, count)}"]
        if path:
            args.extend(["--", path])
        out, err, rc = _run_git(args, self.cwd)
        if rc != 0:
            return f"git log failed:\n{err or out}"
        return out or "No commits yet."


class GitBranchTool(BaseTool):
    name = "git_branch"
    description = (
        "List local branches (current branch marked with '*'), or create a new "
        "branch without switching to it (pass create=<name>). Does not delete "
        "or rename branches. Safe on any branch."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "create": {"type": "string", "description": "If set, create a new branch with this name (does not switch to it)."},
        },
        "required": [],
    }

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, create: str | None = None, **_kwargs) -> str:
        if create:
            out, err, rc = _run_git(["branch", create], self.cwd)
            if rc != 0:
                return f"Failed to create branch '{create}':\n{err or out}"
            return f"Created branch: {create}"

        out, err, rc = _run_git(["branch"], self.cwd)
        if rc != 0:
            return f"git branch failed:\n{err or out}"
        return out or "No branches found."


class GitCheckoutTool(BaseTool):
    name = "git_checkout"
    description = (
        "Switch to an existing branch, or create and switch to a new one "
        "(create=true). Fully unrestricted — can switch to any branch, "
        "including main, at any time. Switching branches alone does not "
        "modify any files."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "Branch name to switch to."},
            "create": {"type": "boolean", "description": "If true, create the branch (git checkout -b). Default: false."},
        },
        "required": ["branch"],
    }

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, branch: str, create: bool = False, **_kwargs) -> str:
        args = ["checkout"]
        if create:
            args.append("-b")
        args.append(branch)
        out, err, rc = _run_git(args, self.cwd)
        if rc != 0:
            return f"Checkout failed:\n{err or out}"
        return err or out or f"Switched to branch: {branch}"


class GitAddTool(BaseTool):
    name = "git_add"
    description = (
        f"Stage specific file paths for the next commit. Only works on "
        f"'{_DAGI_BRANCH_PREFIX}*' branches — refused elsewhere (e.g. main)."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File or directory paths to stage.",
            },
        },
        "required": ["paths"],
    }

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, paths: list[str], **_kwargs) -> str:
        if err := _dagi_branch_guard(self.cwd):
            return err
        if not paths:
            return "Error: paths must be a non-empty list."

        out, err, rc = _run_git(["add", "--"] + paths, self.cwd)
        if rc != 0:
            return f"git add failed:\n{err or out}"

        staged, _, _ = _run_git(["diff", "--cached", "--name-only"], self.cwd)
        lines = ["Staged:"]
        if staged:
            lines.extend(f"  {f}" for f in staged.splitlines())
        else:
            lines.append("  (nothing staged)")
        return "\n".join(lines)


class GitCommitTool(BaseTool):
    name = "git_commit"
    description = (
        f"Commit currently staged changes (use git_add first — this tool does "
        f"NOT stage anything itself). Only works on '{_DAGI_BRANCH_PREFIX}*' "
        f"branches — refused elsewhere. Errors if nothing is staged. Returns "
        f"the commit hash and list of committed files."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Commit message"},
        },
        "required": ["message"],
    }

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, message: str, **_kwargs) -> str:
        if err := _dagi_branch_guard(self.cwd):
            return err

        staged, _, _ = _run_git(["diff", "--cached", "--name-only"], self.cwd)
        if not staged.strip():
            return "Nothing staged to commit — use git_add to stage files first."

        out, err, rc = _run_git(["commit", "-m", message], self.cwd)
        if rc != 0:
            return f"Commit failed:\n{err or out}"

        hash_out, _, _ = _run_git(["rev-parse", "--short", "HEAD"], self.cwd)
        files_out, _, _ = _run_git(
            ["diff-tree", "--no-commit-id", "-r", "--name-only", "HEAD"], self.cwd
        )

        lines = [f"Committed: {hash_out}"]
        if files_out:
            lines.append("Files:")
            lines.extend(f"  {f}" for f in files_out.splitlines())
        return "\n".join(lines)


class GitResetTool(BaseTool):
    name = "git_reset"
    description = (
        f"Reset the current branch to a prior ref (default HEAD~1). mode is "
        f"'soft' (keep changes staged), 'mixed' (keep changes unstaged, "
        f"default), or 'hard' (discard changes entirely). clean=true also "
        f"removes untracked files (git clean -fd). Only works on "
        f"'{_DAGI_BRANCH_PREFIX}*' branches — refused elsewhere."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Commit-ish to reset to. Default: HEAD~1."},
            "mode": {"type": "string", "enum": ["soft", "mixed", "hard"], "description": "Reset mode. Default: mixed."},
            "clean": {"type": "boolean", "description": "Also remove untracked files. Default: false."},
        },
        "required": [],
    }

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, ref: str = "HEAD~1", mode: str = "mixed", clean: bool = False, **_kwargs) -> str:
        if err := _dagi_branch_guard(self.cwd):
            return err
        if mode not in _VALID_RESET_MODES:
            return f"Error: mode must be one of {sorted(_VALID_RESET_MODES)}, got {mode!r}."

        before, _, _ = _run_git(["status", "--porcelain"], self.cwd)

        out, err, rc = _run_git(["reset", f"--{mode}", ref], self.cwd)
        if rc != 0:
            return f"Reset failed:\n{err or out}"

        lines = [f"Reset ({mode}) to {ref}."]
        if before.strip():
            lines.append("Working tree changes before reset:")
            lines.extend(f"  {line[3:]}" for line in before.splitlines() if line.strip())

        if clean:
            clean_out, _, _ = _run_git(["clean", "-fd"], self.cwd)
            if clean_out:
                lines.append("Removed untracked files:")
                lines.extend(f"  {f}" for f in clean_out.splitlines())

        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_git_tools.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add tools/git.py tests/test_git_tools.py
git commit -m "feat: expand git tools (diff/log/branch/checkout/add/reset), scope commit/add/reset to dagi/* branches"
```

---

### Task 3: Wire new tools into the main tool registry

**Files:**
- Modify: `agent/tools.py:29` (import line), `agent/tools.py:288-290` (registration block)
- Test: `tests/test_git_tools_registration.py`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_git_tools_registration.py — Git tools appear in (or are absent from)
the main tool registry as expected."""
from __future__ import annotations

from pathlib import Path

from agent.tools import create_tool_registry


class TestGitToolsRegistration:
    def test_all_new_git_tools_registered(self):
        reg = create_tool_registry(cwd=Path("."))
        names = {n for n, _ in reg.list_tools()}
        expected = {
            "git_status", "git_diff", "git_log", "git_branch",
            "git_checkout", "git_add", "git_commit", "git_reset",
        }
        assert expected.issubset(names)

    def test_git_rollback_not_registered(self):
        reg = create_tool_registry(cwd=Path("."))
        names = {n for n, _ in reg.list_tools()}
        assert "git_rollback" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_git_tools_registration.py -v`
Expected: FAIL — `git_diff`, `git_log`, etc. not in names (AssertionError on subset check)

- [ ] **Step 3: Update `agent/tools.py`**

Change the import at line 29 from:

```python
from tools.git import GitCommitTool, GitRollbackTool, GitStatusTool
```

to:

```python
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
```

Change the registration block at lines 288-290 from:

```python
        reg.register(GitStatusTool(cwd=cwd))
        reg.register(GitCommitTool(cwd=cwd))
        reg.register(GitRollbackTool(cwd=cwd))
```

to:

```python
        reg.register(GitStatusTool(cwd=cwd))
        reg.register(GitDiffTool(cwd=cwd))
        reg.register(GitLogTool(cwd=cwd))
        reg.register(GitBranchTool(cwd=cwd))
        reg.register(GitCheckoutTool(cwd=cwd))
        reg.register(GitAddTool(cwd=cwd))
        reg.register(GitCommitTool(cwd=cwd))
        reg.register(GitResetTool(cwd=cwd))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_git_tools_registration.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full existing test suite to check for regressions**

Run: `conda run -n dagi python -m pytest tests/ -v`
Expected: PASS — no test should reference `GitRollbackTool` (confirmed via Task 2's `TestGitRollbackRemoved`); if any other test imports it, fix that test in this step.

- [ ] **Step 6: Commit**

```bash
git add agent/tools.py tests/test_git_tools_registration.py
git commit -m "feat: register expanded git toolkit, drop git_rollback from agent registry"
```

---

### Task 4: Auto-branch on entering plan mode

**Files:**
- Modify: `tools/plan_mode.py:9-29` (`EnterPlanModeTool`)
- Modify: `agent/loop.py:20` (import), `agent/loop.py:617-662` (`_handle_enter_plan_mode`)
- Test: `tests/test_plan_mode_branch.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_plan_mode_branch.py -v`
Expected: FAIL — `TypeError` or assertion failures, since `task_summary` isn't read/required yet and no branch is created.

- [ ] **Step 3: Update `tools/plan_mode.py`**

Replace `EnterPlanModeTool` (lines 9-29) with:

```python
class EnterPlanModeTool(BaseTool):
    name = "enter_plan_mode"
    description = (
        "Switch to plan mode. Restricts tools to read/grep/find and plan-file write only. "
        "Pass mode='interactive' when invoked by the user (plan requires approval before execution). "
        "Pass mode='autonomous' when DAGI initiates internally (plan is auto-approved). "
        "task_summary is a short kebab-case slug describing the task (e.g. 'fix-git-tools') — "
        "it seeds the plan title and names the git branch auto-created for this task."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["interactive", "autonomous"],
                "description": "interactive: user must approve the plan. autonomous: plan is auto-approved.",
            },
            "task_summary": {
                "type": "string",
                "description": "Short kebab-case slug summarizing the task, e.g. 'fix-git-tools'.",
            },
        },
        "required": ["mode", "task_summary"],
    }

    def run(self, mode: str, task_summary: str) -> str:  # noqa: ARG002
        return f"{ENTER_PLAN_MODE_SENTINEL}:{mode}"
```

- [ ] **Step 4: Update `agent/loop.py` import**

Change line 20 from:

```python
from tools.plan_mode import ENTER_PLAN_MODE_SENTINEL, EXIT_PLAN_MODE_SENTINEL
```

to:

```python
from agent._git_branch import create_task_branch
from tools.plan_mode import ENTER_PLAN_MODE_SENTINEL, EXIT_PLAN_MODE_SENTINEL
```

- [ ] **Step 5: Update `_handle_enter_plan_mode` in `agent/loop.py` (lines 617-662)**

Replace the full method with:

```python
    def _handle_enter_plan_mode(self, args: dict) -> str:
        mode = args.get("mode", "interactive")
        task_summary = (args.get("task_summary") or "").strip()
        if not task_summary:
            return "Error: task_summary is required when entering plan mode."

        interactive = mode != "autonomous"
        dagi_root = DAGI_ROOT
        plans_dir = self.config.project_path / ".dagi" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_dir = plans_dir / f"plan_{ts}"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text(
            f"# Plan: {task_summary}\n\n"
            "## Context\n\n\n"
            "## Approach\n\n\n"
            "## Files to Modify\n\n\n"
            "## Subtasks\n\n"
            "### Subtask 1: [ ] \n"
            "**Goal:** \n"
            "**Requirements:**\n"
            "- \n"
            "**Acceptance Criteria:**\n"
            "- \n"
            "#### Tests\n"
            "<!-- Filled by main agent before executing this subtask — do NOT write tests here -->\n\n"
            "## Notes\n\n"
            "## Verification\n\n"
            "## Execution Protocol\n\n",
            encoding="utf-8",
        )

        branch_name: str | None = None
        try:
            branch_name = create_task_branch(self.config.project_path, task_summary, plan_dir.name)
        except RuntimeError as e:
            self.callbacks.on_assistant_text(f"[git] Could not create task branch: {e}")

        if branch_name:
            branch_note = f"**Branch:** `{branch_name}`"
        else:
            branch_note = "**Branch:** (no git repository detected — skipping git workflow)"

        self._handle_switch_model("plan", {"reason": "entering plan mode"})
        to_name = self.config.display_name or self.config.model

        self.callbacks.on_assistant_text(
            f"Entering plan mode — switching to advanced model ({to_name}).\n\n"
            f"**Plan file:** `{plan_file}`\n\n**Mode:** {mode}\n\n{branch_note}"
        )

        self._rebuild_for_plan_mode(dagi_root, plan_file, interactive=interactive)

        return (
            f"Plan mode activated ({mode} mode). Advanced model: {to_name}.\n\n"
            f"Plan file: {plan_file}\n\n"
            f"{branch_note}\n\n"
            f"Tools restricted to: read, grep, find, write/edit (plan file only), "
            f"web_research, skill, run_skill_script, ask_user, show_plan, exit_plan_mode."
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_plan_mode_branch.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Run the full existing test suite to check for regressions**

Run: `conda run -n dagi python -m pytest tests/ -v`
Expected: PASS. Pay particular attention to any existing test that calls `enter_plan_mode`/`_handle_enter_plan_mode` without a `task_summary` — none currently exist (confirmed by grep in the exploration phase), but if one turns up, add `task_summary` to its call args.

- [ ] **Step 8: Commit**

```bash
git add tools/plan_mode.py agent/loop.py tests/test_plan_mode_branch.py
git commit -m "feat: auto-create dagi/<slug>_<plan_id> branch when entering plan mode"
```

---

### Task 5: Update `plan-work-review` skill — per-subtask commits and merge reminder

**Files:**
- Modify: `.dagi/skills/plan-work-review/SKILL.md`

- [ ] **Step 1: Update Step 1 (Enter Plan Mode) to pass `task_summary`**

Find this line (Phase 1, Step 1):

```markdown
Call `enter_plan_mode(mode="interactive")` if this skill was invoked by the user (slash command or explicit request). Call `enter_plan_mode(mode="autonomous")` if DAGI initiated this internally.
```

Replace with:

```markdown
Call `enter_plan_mode(mode="interactive", task_summary="<short-kebab-case-slug>")` if this skill was invoked by the user (slash command or explicit request). Call `enter_plan_mode(mode="autonomous", task_summary="<short-kebab-case-slug>")` if DAGI initiated this internally. `task_summary` should be a short kebab-case slug capturing the task (e.g. `"fix-login-bug"`) — it seeds the plan title and names the git branch DAGI automatically creates and checks out for this task. If the tool result's `**Branch:**` line shows "no git repository detected", DAGI has no git workflow for this task — proceed with planning normally, just skip all git_* steps below.
```

- [ ] **Step 2: Add per-subtask commit instructions to Phase 2, Step 4 ("If PASS" branch)**

Find this block:

```markdown
**If PASS:**
- Edit `plan.md` and mark the subtask `[x] complete`
- Append a PASS entry to `cycle_log.md` in the plan subfolder
- Update the `## Notes` section of `plan.md` with salient findings from the review
- Proceed to the next subtask
```

Replace with:

```markdown
**If PASS:**
- Edit `plan.md` and mark the subtask `[x] complete`
- If this task has a git branch (see Step 1 — skip this bullet if none was created): call `git_add` with the list of files this subtask touched, then `git_commit` with a message summarizing the subtask (e.g. `"Subtask 2: Add login endpoint"`). Do this every time a subtask passes review — never batch commits across subtasks.
- Append a PASS entry to `cycle_log.md` in the plan subfolder
- Update the `## Notes` section of `plan.md` with salient findings from the review
- Proceed to the next subtask
```

- [ ] **Step 3: Add merge-reminder to Phase 2, Step 5 ("Complete the Plan")**

Find this block:

```markdown
### Step 5 — Complete the Plan
Once **every** subtask is resolved (all markers are `[x]` or `[!]` — none remain `[ ]` or `[~]`), call `complete_plan()`.

This clears the active plan reference from the loop. After this call:
- Future subagent handoffs route back to `.dagi/handoffs/`
- The TUI plan panel clears
- The plan document is preserved on disk at its original path — reference it by path if needed

Do NOT call `complete_plan()` mid-cycle or before all subtasks are settled.
```

Replace with:

```markdown
### Step 5 — Complete the Plan
Once **every** subtask is resolved (all markers are `[x]` or `[!]` — none remain `[ ]` or `[~]`), call `complete_plan()`.

This clears the active plan reference from the loop. After this call:
- Future subagent handoffs route back to `.dagi/handoffs/`
- The TUI plan panel clears
- The plan document is preserved on disk at its original path — reference it by path if needed

Do NOT call `complete_plan()` mid-cycle or before all subtasks are settled.

**After `complete_plan()`, if this task has a git branch:** finish any remaining housekeeping first (e.g. invoke the `update-project-context` skill if the change is significant), then report a summary to the user covering:
- The branch name (from Step 1's `**Branch:**` line)
- Number of commits made and files changed (use `git_log` and `git_diff main...HEAD --name-only` via `git_diff(path=...)` calls, or summarize from `cycle_log.md`)
- A reminder that the branch is ready for the user to review and merge manually — DAGI does not merge branches itself.

Do NOT attempt to merge the branch, switch back to `main`, or delete the task branch. Leave it exactly as-is for the user.
```

- [ ] **Step 4: Verify the edits landed correctly**

Run: `conda run -n dagi python -c "
content = open('.dagi/skills/plan-work-review/SKILL.md', encoding='utf-8').read()
assert 'task_summary=' in content
assert 'git_add' in content and 'git_commit' in content
assert 'DAGI does not merge branches itself' in content
print('OK — all three edits present')
"`
Expected: `OK — all three edits present`

- [ ] **Step 5: Commit**

```bash
git add .dagi/skills/plan-work-review/SKILL.md
git commit -m "docs: wire git workflow into plan-work-review skill (task_summary, per-subtask commits, merge reminder)"
```

---

### Task 6: Update project documentation

**Files:**
- Modify: `PROJECT_CONTEXT.md` (Key Files & Directories, Notable Points, Terms & Language sections)
- Modify: `TODO.md` (mark relevant open item, add completed entry)
- Modify: `README.md` (if it documents available tools/git behavior — check first)

- [ ] **Step 1: Check whether README.md documents the tool list**

Run: `conda run -n dagi python -c "
content = open('README.md', encoding='utf-8').read()
print('git_status' in content, 'git_commit' in content, 'git_rollback' in content)
"`

If any of these are `True`, update the relevant section to reflect the new tool list (`git_status`, `git_diff`, `git_log`, `git_branch`, `git_checkout`, `git_add`, `git_commit`, `git_reset` — no `git_rollback`, no merge tool) and the auto-branch-per-plan behavior. If all are `False`, skip this file.

- [ ] **Step 2: Invoke the update-project-context skill**

This is a skill invocation, not a manual edit — run it to regenerate `PROJECT_CONTEXT.md` accurately:

Call `skill("update-project-context")`. When it prompts for what changed, describe: "Implemented the DAGI git workflow — expanded tools/git.py (git_diff, git_log, git_branch, git_checkout, git_add, git_reset added; git_commit rewritten to require explicit staging; git_rollback removed), added agent/_git_branch.py for plan-mode auto-branching (dagi/<slug>_<plan_id>), added required task_summary param to enter_plan_mode, and updated plan-work-review skill for per-subtask commits + merge reminder. Spec at docs/superpowers/specs/2026-07-12-dagi-git-workflow-design.md, plan at docs/superpowers/plans/2026-07-12-dagi-git-workflow.md."

- [ ] **Step 3: Update TODO.md**

Find the archived entry:

```markdown
- GNHF skill (`git_status`, `git_commit`, `git_rollback`) · `done:~2026-05-03`
```

Leave it as historical record (it's accurate for what existed then), and add a new entry to the Completed section (near the top, following the existing format for recent completions):

```markdown
- [x] DAGI git workflow — expanded git toolkit (`git_diff`, `git_log`, `git_branch`, `git_checkout`, `git_add`, `git_reset` added; `git_commit` requires explicit staging; `git_rollback` removed from agent registry), auto-branch per plan-mode task (`dagi/<slug>_<plan_id>`), `dagi/*` whitelist guard on add/commit/reset, per-subtask commits via plan-work-review skill, no auto-merge (user-only). Accepted limitation: BashTool remains an unrestricted bypass of the dagi/* guard. (2026-07-12)
```

- [ ] **Step 4: Commit**

```bash
git add PROJECT_CONTEXT.md TODO.md README.md
git commit -m "docs: update project docs for DAGI git workflow"
```

---

## Final Verification

- [ ] Run the complete test suite once more end-to-end:

Run: `conda run -n dagi python -m pytest tests/ -v`
Expected: All tests PASS, including every new test file added in Tasks 1-4.

- [ ] Manually sanity-check the guard behavior on the real repo (read-only checks, safe to run):

Run: `git branch --show-current`
Expected: prints the current branch — confirms the repo itself is in a normal state after the test suite ran (tests operate in `tmp_path` fixtures, never on the real repo, but this is a cheap final sanity check).
