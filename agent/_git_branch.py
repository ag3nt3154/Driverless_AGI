"""agent/_git_branch.py — Git branch helpers.

Isolated helper functions for creating task branches and querying
the current branch. Used by the /plan skill to create dedicated
`dagi/<slug>_<plan_id>` branches for planned tasks.
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


def get_current_branch(cwd: Path) -> str | None:
    """Return the current branch name, or None if not in a git repo."""
    if not is_git_repo(cwd):
        return None
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


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
