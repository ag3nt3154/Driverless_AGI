---
name: merging-git-branch
description: Finish a fully verified task branch through the user's explicit local merge or keep-as-is decision; return the outcome to enter-workflow.
---

# Finish the branch

Only the main agent runs this stage after delivery's integrated verification and independent
final review. Read the task/parent names, checkout, plan, and current verification evidence
from `enter-workflow`. Inspect Git status and worktrees; never infer the target from upstream
or assume main. Reuse valid tests, rerunning required checks only when changed or missing.

The owner must finish accepted task commits before the merge offer. Report unresolved
changes/failed checks as blockers; do not commit, stash, or discard them here. Resolve a
missing parent or merge strategy before presenting the concrete action.

Present the completed branch and only these two choices using an available permitted
question mechanism or a plain final-message question:

- Merge the named task branch into the named parent locally, using the stated strategy.
- Keep the branch and workspace as-is.

Wait for an explicit choice. Initial design, implementation, and subtask-commit approval
does not authorize merging; silence and automated continuations do not answer this question.
For detached HEAD, keeping is possible; obtain a named-branch decision before merging.

For merge, use the correct checkout and agreed strategy, verify the actual Git result, and
run required checks on the merged result. On interruption inspect history before repeating
the merge. Conflicts or failed checks return `blocked`; distinguish a merge that happened
but failed verification. Keep work intact. For keep, preserve it and report its location.

Return `merged`, `kept`, or `blocked`, with branch names, checkout, verification, and remaining
work. Do not recursively invoke the owner. It records finishing and performs wiki/context
closure in the corresponding checkout. Do not push, create PRs, pull automatically, reset,
delete branches, or remove worktrees. Those actions require their own explicit authorization.
