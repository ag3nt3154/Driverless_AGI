---
name: merging-git-branch
description: Draft sample for finishing a verified task branch and offering a user-confirmed merge.
---

# merging-git-branch

Draft for discussion. This is a minimal sample; detailed merge policy remains undecided.

## Place in the workflow

`enter-workflow` invokes this after `deliver` returns successful verification and final
review. The main agent runs it with the task branch, recorded parent branch, and evidence.
This skill owns the final merge offer; delivery does not merge or detach first.

## Simple sample

1. Inspect repository status and both branch names. Confirm the task changes and
   verification evidence are current; report blockers or unrelated uncommitted work.
2. Show the result and ask: "Merge `<task-branch>` into `<parent-branch>`, or leave
   the verified branch unmerged?" Never infer merge permission from design approval.
3. If the target is unknown, obtain it before proposing a concrete merge. If the user
   declines, preserve the branch and return "verified, left unmerged".
4. After explicit approval, merge the agreed branches using the agreed strategy.
   Report conflicts or failures; do not silently discard changes or claim success.
5. Verify the merged result and return the outcome and evidence to `enter-workflow`.
   The caller records final wiki/plan status and detaches only after closure succeeds.

Pushing and branch deletion are separate actions requiring their own authorization.

## Still to decide

- Merge versus squash, and fast-forward policy.
- Conflicts, parent changes since verification, and checks after merging.
- Final commits, cleanup, cancellation, and interrupted-operation recovery.
