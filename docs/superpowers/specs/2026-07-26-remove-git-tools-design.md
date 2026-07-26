# Remove Dedicated Git Tools — Design Spec

**Date:** 2026-07-26  
**Status:** Approved  
**Motivation:** Simplicity — fewer tools = smaller tool list, cheaper prompts, less maintenance.

---

## Decision

Remove the 8 dedicated git tools (`tools/git/`) and rely entirely on `BashTool` for git operations. The `dagi/*` branch workflow is preserved, now documented as prompt rules rather than enforced by a code guard.

## What Changes

| Area | Before | After |
|------|--------|-------|
| `tools/git/` | 8 tool classes with branch guard | Deleted |
| `agent/tools.py` | Imports + registers 8 git tools | Removed |
| `.dagi/config.yaml` | `git_status`, `git_commit`, `git_rollback` in allowlist | Removed |
| `tests/test_git_tools.py` | Tests for the 8 tools | Deleted |
| `tests/test_git_tools_registration.py` | Asserts tools registered | Deleted |
| `AGENTS.md` | Branch guard rule referencing tools | Replaced with workflow rules |

## What Does NOT Change

- `agent/_git_branch.py` — internal helper that auto-creates `dagi/*` branch on `enter_plan_mode`. Stays.
- `tests/test_git_branch.py` — tests for `_git_branch.py`. Stays.

## Git Workflow (prompt rules, in AGENTS.md)

1. **On task start** — run `git status` + `git branch --show-current` via bash. If there are uncommitted/unstaged changes or DAGI is not on the intended base branch, ask the user: stash, commit, or checkout a different base?
2. **Create branch** — `git checkout -b dagi/<task-name>` from the confirmed base.
3. **Commits** — 1 commit per subtask completion + 1 commit after updating project context. Use Conventional Commits format (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `perf:`).
4. **On task end** — stay on `dagi/*` branch. Ask the user if they want to merge back to the previous branch. DAGI never merges unilaterally.

## Accepted Limitation

`BashTool` remains unrestricted. There is no code-level enforcement of the `dagi/*` restriction — it is a prompt convention, as was effectively the case before (BashTool already bypassed the guard).
