import subprocess
from pathlib import Path

from agent.base_tool import BaseTool

_DAGI_BRANCH = "dagi"


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


def _branch_guard(cwd: Path) -> str | None:
    branch = _current_branch(cwd)
    if branch != _DAGI_BRANCH:
        return (
            f"Error: this tool only operates on the '{_DAGI_BRANCH}' branch. "
            f"Currently on '{branch}'. "
            f"Switch with: git checkout {_DAGI_BRANCH}  "
            f"(or: git checkout -b {_DAGI_BRANCH} to create it)"
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


class GitCommitTool(BaseTool):
    name = "git_commit"
    description = (
        f"Stage all changes and commit on the '{_DAGI_BRANCH}' branch. "
        f"Hard-errors on any other branch. "
        "Returns the commit hash and list of committed files."
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
        if err := _branch_guard(self.cwd):
            return err

        status, _, _ = _run_git(["status", "--porcelain"], self.cwd)
        if not status.strip():
            return "Nothing to commit — working tree is clean."

        _run_git(["add", "-A"], self.cwd)
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


class GitRollbackTool(BaseTool):
    name = "git_rollback"
    description = (
        f"Hard-reset to HEAD and clean untracked files on the '{_DAGI_BRANCH}' branch. "
        f"Hard-errors on any other branch. "
        "Returns the list of discarded files."
    )
    _parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, **_kwargs) -> str:
        if err := _branch_guard(self.cwd):
            return err

        status, _, _ = _run_git(["status", "--porcelain"], self.cwd)
        if not status.strip():
            return "Nothing to rollback — working tree is clean."

        changed = [line[3:] for line in status.splitlines() if line.strip()]

        _run_git(["reset", "--hard", "HEAD"], self.cwd)
        _run_git(["clean", "-fd"], self.cwd)

        lines = ["Rolled back to HEAD. Discarded:"]
        lines.extend(f"  {f}" for f in changed)
        return "\n".join(lines)
