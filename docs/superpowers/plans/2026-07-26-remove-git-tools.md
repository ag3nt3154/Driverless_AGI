# Remove Dedicated Git Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the 8 dedicated git tools (`tools/git/`) from DAGI and replace them with BashTool + system-prompt workflow rules.

**Architecture:** Delete `tools/git/` and its registrations in `agent/tools.py`. Remove now-stale git tool names from `.dagi/config.yaml`. Delete the two git-tool test files. Update `AGENTS.md` with the new 4-step git workflow. `agent/_git_branch.py` (auto-branch on plan-mode entry) is untouched.

**Tech Stack:** Python, pytest, git, YAML

---

## File Map

| File | Action |
|------|--------|
| `tools/git/_git.py` | **Delete** |
| `tools/git/__init__.py` | **Delete** |
| `agent/tools.py` | **Modify** — remove import block + 8 `reg.register()` calls |
| `.dagi/config.yaml` | **Modify** — remove `git_status`, `git_commit`, `git_rollback` from `tools:` |
| `tests/test_git_tools.py` | **Delete** |
| `tests/test_git_tools_registration.py` | **Delete** (replace with a single negative assertion) |
| `AGENTS.md` | **Modify** — replace old git rules with 4-step workflow |

---

### Task 1: Remove git tool imports and registrations from `agent/tools.py`

**Files:**
- Modify: `agent/tools.py:27-36` (import block), `agent/tools.py:214-221` (registration block)

- [ ] **Step 1: Remove the git import block**

In `agent/tools.py`, delete lines 27–36:

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

- [ ] **Step 2: Remove the 8 git tool registrations**

In `agent/tools.py`, delete lines 214–221 (inside the `else` block):

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

- [ ] **Step 3: Verify the file is syntactically valid**

```
conda run -n dagi python -c "from agent.tools import create_tool_registry; print('ok')"
```

Expected: `ok` with no import errors.

---

### Task 2: Delete the `tools/git/` directory

**Files:**
- Delete: `tools/git/_git.py`, `tools/git/__init__.py`

- [ ] **Step 1: Delete both files**

```bash
rm tools/git/_git.py tools/git/__init__.py
rmdir tools/git
```

- [ ] **Step 2: Confirm no remaining imports**

```bash
grep -r "from tools.git" . --include="*.py"
```

Expected: no output (zero matches).

---

### Task 3: Delete the git tool test files

**Files:**
- Delete: `tests/test_git_tools.py`, `tests/test_git_tools_registration.py`

- [ ] **Step 1: Delete both test files**

```bash
rm tests/test_git_tools.py tests/test_git_tools_registration.py
```

- [ ] **Step 2: Confirm test suite still collects cleanly**

```
conda run -n dagi pytest --collect-only -q 2>&1 | tail -5
```

Expected: no `ImportError` or `ModuleNotFoundError`. Collection may warn about removed files — that's fine as long as it doesn't error.

---

### Task 4: Update `.dagi/config.yaml` — remove stale git tool names

**Files:**
- Modify: `.dagi/config.yaml:41-44`

- [ ] **Step 1: Remove the git tools section**

In `.dagi/config.yaml`, delete the entire git tools block (lines 41–44):

```yaml
  # ── Git tools ────────────────────────────────────────────────────────────────
  - git_status              # Show current git status / diff
  - git_commit              # Stage and commit changes
  - git_rollback            # Revert uncommitted changes
```

Note: these names (`git_status`, `git_commit`, `git_rollback`) were already mismatched with the actual registered tool names — so this is a cleanup of stale config, not a behaviour change.

- [ ] **Step 2: Verify config loads without error**

```
conda run -n dagi python -c "from agent.config_loader import load_config; c = load_config(); print(c.tools)"
```

Expected: a list of tool names that does NOT include `git_status`, `git_commit`, or `git_rollback`.

---

### Task 5: Update `AGENTS.md` — replace git rules with the new workflow

**Files:**
- Modify: `AGENTS.md` (Rules section, Notes & Terms section)

- [ ] **Step 1: Replace the old git rules in the Rules section**

In `AGENTS.md`, find the Rules section. Replace:

```markdown
- `git_add`/`git_commit`/`git_reset` only operate on `dagi/*` branches; raw `git` via `BashTool` is unrestricted.
```

With the 4-step workflow:

```markdown
## Git Workflow

All git operations use `bash`. No dedicated git tools exist. Follow this workflow at the start of every task:

1. **Check state** — run `git status` and `git branch --show-current`. If there are uncommitted or unstaged changes, or you are not on the intended base branch, **ask the user**: stash, commit, or checkout a different base?
2. **Create branch** — `git checkout -b dagi/<task-name>` from the confirmed base.
3. **Commit discipline** — 1 commit per subtask completion + 1 commit after updating project context. Use [Conventional Commits](https://www.conventionalcommits.org/) format: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `perf:`.
4. **On task end** — stay on `dagi/*` branch. Ask the user if they want to merge back to the previous branch. **Never merge unilaterally.**
```

- [ ] **Step 2: Update the Notes & Terms entry for `dagi/*` branch**

Find in the Notes & Terms section:

```markdown
- **`dagi/*` branch**: only prefix where `git_add`/`git_commit`/`git_reset` work (dedicated tools only; `BashTool` bypasses).
```

Replace with:

```markdown
- **`dagi/*` branch**: all plan-mode work lands here. Auto-created by `agent/_git_branch.py` on `enter_plan_mode`. DAGI commits here and asks the user before merging back. See Git Workflow section in Rules.
```

- [ ] **Step 3: Verify AGENTS.md has no remaining references to removed tools**

```bash
grep -n "git_add\|git_commit\|git_reset\|git_status\|git_diff\|git_log\|git_branch\|git_checkout\|GitAddTool\|GitCommitTool" AGENTS.md
```

Expected: no matches.

---

### Task 6: Run the full test suite and commit

**Files:** none (verification + commit only)

- [ ] **Step 1: Run the full test suite**

```
conda run -n dagi pytest -x -q
```

Expected: all tests pass. The deleted git tool tests will simply be gone — no failures expected.

- [ ] **Step 2: Commit all changes**

```bash
git add agent/tools.py .dagi/config.yaml AGENTS.md docs/superpowers/specs/2026-07-26-remove-git-tools-design.md docs/superpowers/plans/2026-07-26-remove-git-tools.md
git commit -m "refactor: remove dedicated git tools, replace with bash + workflow rules"
```

- [ ] **Step 3: Update project context**

Invoke `update-project-context` skill to keep AGENTS.md in sync with the changes.
