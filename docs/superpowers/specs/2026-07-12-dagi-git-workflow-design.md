# DAGI Git Workflow — Design

> Status: approved (design phase) | Author: Claude-chan (via brainstorming session) | Date: 2026-07-12

## Problem Statement

DAGI currently has three git tools (`tools/git.py`): `git_status` (read-only, safe), `git_commit`
(auto `add -A` + commit, guarded to a single hardcoded branch named `dagi`), and `git_rollback`
(`reset --hard` + `clean -fd`, same hardcoded-branch guard). This is too coarse:

- There's no `git_diff`, `git_log`, `git_branch`, `git_add`, or `git_checkout` — DAGI can't inspect
  history or diffs without falling back to raw `bash("git ...")`.
- The single fixed branch name `dagi` doesn't scale to multiple concurrent/sequential tasks — every
  task collides on the same branch.
- `git_commit`'s `add -A` is not deliberate — it stages and commits everything in the working tree
  regardless of what the current subtask actually touched.
- `git_rollback` performs a hard, irreversible reset and was exposed to the agent with no additional
  confirmation step.

Goal: give DAGI a **basic, everyday git toolkit** (status/diff/log/branch/checkout/add/commit/reset)
that it can use freely within a safe lane, while operations that are complex or affect the
codebase in a hard-to-reverse way across the *shared* trunk (merge, force-push, branch
delete/rename) remain something only the user does by hand.

## Scope

- **In scope:** tool additions/changes in `tools/git.py`, wiring in `agent/tools.py`, the
  auto-branch lifecycle hook in `agent/loop.py` (`enter_plan_mode`), and the skill instructions in
  `.dagi/skills/plan-work-review/SKILL.md` that drive per-subtask commits.
- **Out of scope:** sandboxing `BashTool` (tracked separately — see Accepted Limitations), building
  a `git_merge` tool, any UI/TUI changes to surface branch state.

## Architecture

### Trust boundary: plan mode

Auto-branching hooks into the **existing plan-mode boundary**, not into every tool call. Plan mode
already restricts the tool surface via `_rebuild_for_plan_mode` in `agent/loop.py`; this design adds
one more side effect to that same choke point (`_handle_enter_plan_mode`) rather than introducing a
new enforcement mechanism elsewhere.

```
enter_plan_mode(mode, task_summary)
    │
    ├─ create .dagi/plans/plan_{ts}/plan.md   (existing behavior, unchanged)
    │
    └─ NEW: if git repo detected:
             git checkout -b dagi/{task_summary}_{plan_{ts}}   (from current HEAD)
           else:
             skip silently, notify via on_assistant_text, plan mode proceeds as today
```

- Applies to **both** `interactive` and `autonomous` plan modes (scheduler-initiated plans get
  branches too).
- Branches off **whatever branch is currently checked out** — no forced switch to `main` first.
- Trigger scope is **plan-mode tasks only**. Quick one-off requests outside plan mode do not create
  a branch; they operate on whatever branch is already checked out (git tools remain usable there,
  subject to the guards below).

### Tool inventory (`tools/git.py`)

| Tool | Status | Signature | Guard |
|---|---|---|---|
| `git_status` | unchanged | `status()` | none |
| `git_diff` | **new** | `diff(staged: bool = False, path: str \| None = None)` | none |
| `git_log` | **new** | `log(count: int = 10, path: str \| None = None)` | none |
| `git_branch` | **new** | `branch(create: str \| None = None)` — no args lists branches (current marked); `create=` creates without switching | none |
| `git_checkout` | **new** | `checkout(branch: str, create: bool = False)` | none — fully unrestricted, any branch, any time |
| `git_add` | **new** | `add(paths: list[str])` — explicit paths, no implicit `-A` | `dagi/*` whitelist |
| `git_commit` | **modified** | `commit(message: str)` — drops `add -A`; errors if nothing staged | `dagi/*` whitelist |
| `git_reset` | **new, replaces `git_rollback`** | `reset(ref: str = "HEAD~1", mode: "soft"\|"mixed"\|"hard" = "mixed", clean: bool = False)` — `clean=True` also runs `git clean -fd` | `dagi/*` whitelist |

`git_rollback` (`GitRollbackTool`) is removed from the registry in `agent/tools.py`; `git_reset`
replaces it with the same capability (including hard reset) but scoped by the whitelist below
instead of the old single-hardcoded-branch check.

### Guard policy: whitelist, not blocklist

`git_add`, `git_commit`, and `git_reset` all use the same guard:

```python
def _dagi_branch_guard(cwd: Path) -> str | None:
    branch = _current_branch(cwd)
    if not branch.startswith("dagi/"):
        return (
            f"Error: this tool only operates on 'dagi/*' branches. "
            f"Currently on '{branch}'."
        )
    return None
```

This replaces the old approach (block a fixed list of protected names) with a whitelist (only
`dagi/*` branches are allowed). A whitelist fails closed — any branch not created via the
`dagi/*` convention is refused by default, including `main`, `master`, and any pre-existing feature
branch DAGI happens to be checked out on. `git_checkout` itself has **no** guard: switching
branches alone isn't destructive, and DAGI needs to be able to look around freely (including
checking out `main` to compare, or checking out a branch it doesn't own to inspect it).

### Per-subtask commits (skill-instructed, not harness-automatic)

There is no dedicated "mark subtask complete" tool today — the LLM edits `plan.md` directly per
`.dagi/skills/plan-work-review/SKILL.md`, flipping the status marker (`[ ]` → `[~]` → `[x]`/`[!]`).
Because that step is already skill-instructed (not harness-intercepted), the commit step is added
the same way, immediately after the existing "mark subtask complete" instruction:

> After marking a subtask `[x]` complete (or `[!]` failed with partial work worth preserving),
> call `git_add` with the files touched by this subtask, then `git_commit` with a message
> summarizing the subtask.

This keeps the same authority pattern the skill already uses for the worker → review → mark
sequence, rather than adding file-watching logic to the general-purpose `EditTool`/`WriteTool`
(which would be a layering violation — those tools have no reason to know about plan semantics).

### Plan completion and cancellation

- `complete_plan()` behavior is unchanged. The skill/system-prompt is updated so that after
  `complete_plan`, DAGI finishes any remaining housekeeping (e.g. `update-project-context`), then
  reports a summary — branch name, commit count, files changed — and reminds the user to review and
  merge manually. **No merge tool exists**; merging into `main` happens entirely outside DAGI.
- On cancellation (`exit_plan_mode(summary="cancelled")`) the task branch is left exactly as-is —
  no auto-checkout back to the starting branch, no auto-delete. DAGI just names the branch in its
  final message. The user decides by hand whether to keep, delete, or resume it.

## Accepted Limitations

**Bash bypass is not closed by this design.** `BashTool` is registered unrestricted in the same
tool registry (`agent/tools.py:285`) and can run any `git` command directly, including
`git merge`, `git push --force`, or `git reset --hard` on `main` — the same way it already can
today, with or without this change. The `dagi/*` whitelist and the absence of a merge tool are
enforced only at the dedicated-tool layer; they are a **paved path** (structured, parseable,
guardrailed, discoverable via the tool schema), not a security boundary. Closing this fully would
require command-level sandboxing of `BashTool` (already tracked separately in
`PROJECT_CONTEXT.md` under "BashTool is unsandboxed: No command blacklist, no process group kill on
timeout"), which is out of scope for this change.

**Git-repo detection is best-effort.** If `.git` isn't present or the `git` binary isn't on PATH,
auto-branching is skipped silently (a notice is surfaced via `on_assistant_text`) and plan mode
proceeds exactly as it does today with no git workflow at all. No hard failure.

**`task_summary` quality depends on the model.** `enter_plan_mode` gains a required `task_summary`
field (short kebab-case slug) so a meaningful branch name (`dagi/{task_summary}_{plan_{ts}}`) can
be built before `plan.md`'s title is filled in. There's no validation beyond basic slug-sanitization
(lowercase, hyphens, truncate to ~40 chars) — a poorly-chosen slug just produces an ugly but
functional branch name.

## Safety Boundary Summary

| DAGI can do freely, any time | User-only, forever |
|---|---|
| `git_status`, `git_diff`, `git_log` | merge |
| `git_branch` (list/create) | branch delete/rename |
| `git_checkout` (any branch) | force-push |
| `git_add`, `git_commit`, `git_reset` — but only on `dagi/*` branches | any git op directly on `main`/`master` |

## Testing Considerations

- Guard logic (`_dagi_branch_guard`) should be unit-tested independently of subprocess calls (mock
  `_current_branch`), matching the existing pattern for `_branch_guard` today.
- `enter_plan_mode`'s auto-branch step needs a test for the no-git-repo path (skips silently) and
  the git-repo path (branch created and checked out, name matches the expected pattern).
- `git_commit`'s "errors if nothing staged" behavior needs a regression test — this is a behavior
  change from the current `add -A` fallback.
- `git_reset` needs tests for all three modes (`soft`/`mixed`/`hard`) and the `clean` flag,
  independent of the branch guard.

## Open Follow-ups (not blocking this design)

- `BashTool` sandboxing (command blacklist) — separate effort, already on `PROJECT_CONTEXT.md`'s
  shortcomings list.
- Whether `git_branch`/`git_checkout` should be exposed to subagents (currently git tools are
  main-registry-only; the `_tools_from_list` 9-tool cap on subagent registries is tracked
  separately in `TODO.md`).
