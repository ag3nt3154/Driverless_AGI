---
name: merging-git-branch
description: Finish a verified task branch by offering an explicitly confirmed local merge or keep-as-is.
---

# merging-git-branch

Run after `deliver` completes verification and final review. The main agent finishes
the branch, then returns the outcome to `enter-workflow` before final closure.

## Prepare

1. Inspect repository status, task branch, intended parent, and worktree state. Resolve
   missing target information; do not assume main or infer the parent from an upstream.
2. Confirm verification covers the current changes. Reuse valid delivery evidence;
   rerun required checks if it is missing or stale.
3. Report failed checks or uncommitted changes requiring a decision before proceeding.
   Do not commit or stash them here. The owner must finish task-scoped commits under
   the recorded authority before this stage; return a blocker for unresolved changes.

## Ask

Present only these two choices with `ask_user(question=..., no_timeout=true)`:

- Merge `<task-branch>` into `<parent-branch>` locally.
- Keep the branch as-is.

Wait for an explicit choice. Design or implementation approval does not authorize a merge.
For detached HEAD, keeping as-is is possible; agree a named branch before merging.

## Execute

- **Merge:** Use the agreed strategy and correct checkout. Verify the merged result
  using the required project checks. On conflicts or failed checks, preserve the work
  and return a blocker; do not claim the merge is successfully verified.
- **Keep:** Preserve the branch and workspace and report their location.

Do not push, create a PR, automatically pull, force-push, discard changes, delete branches,
or remove worktrees. Cleanup requires separate explicit authorization; directory names
alone do not establish ownership.

## Return

Return `merged`, `kept`, or `blocked`, with branch names, workspace location, verification
commands/results, and remaining work. Distinguish a merge that happened but failed checks.
`enter-workflow` owns final documentation and plan detachment. Do not call it recursively.
