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
