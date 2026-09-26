---
name: deliver
description: Execute an approved implementation plan with independent subtask review, autonomous scoped commits, and integrated verification; return to enter-workflow for finishing.
---

# Delivery stage

When called directly, load `enter-workflow` once with delivery intent. When already called
by that owner, execute this stage and return to it without recursively starting a lifecycle.
Only the main agent delegates, changes shared progress, stages, or commits.

## Entry checks

Read the owner's explicit plan path and its linked spec. Reconcile the checkpoint, actual
checkout/branch, and approval scope before changing files. Never select a different plan to
hide missing state. Read the shared [plan template](../write-plan/references/plan-template.md).
Workspace must already record the branch, parent, starting commit, and artifact directory.
Default branch prefix is `codex/`; honor the owner's recorded explicit project override.

Verify actual user authorization for implementation and task-owned commits, successful
approval wiki checkpoint, and the document commit's actual spec/plan content. A commit
subject or approved label alone proves neither consent nor that later changes were approved.
Planning-only authorization does not permit execution.

Validate the plan has pending/status-bearing subtasks with Goal, Requirements, Acceptance
Criteria, Tests, and concrete steps, plus global constraints and final Verification.
Missing or contradictory prerequisites return a blocker to the owner, not automatic rewriting
or attachment of another plan. Later material scope changes require the owner's resolution.

Reconcile statuses with evidence. `[x]` needs a verified task commit or recorded no-op.
`[~]` can include `review accepted / commit pending` in Notes. Where history proves the expected
commit succeeded, repair stale records rather than rerunning work. Unexplained discrepancies
block dependent action. If only final verification remains, start there; if finishing alone
remains, return to the owner with the valid evidence.

## Worker and reviewer assignments

Read [worker.md](references/worker.md), [reviewer.md](references/reviewer.md), and `do-tdd`
before dispatch. Supply the full relevant protocols/TDD instructions, not just skill names.
These references define the same outcomes for direct main-agent implementation and review.

Use the available native subagent tools, such as `collaboration.spawn_agent` and native
followup/wait tools. Do not create a separate user-owned task as a worker. This user's default
is `gpt-5.6-luna` with medium reasoning; use `fork_turns="none"` and explicit scoped context.
Honor a later explicit user model override. If the required model/delegation is unavailable,
report the review/execution blocker; never fabricate an independent review or switch silently.

Each worker gets the exact checkout, owned files, subtask, relevant global constraints,
interfaces, acceptance criteria, test commands, and full TDD instructions. It must not edit
the plan, delegate, stage, commit, install globally, or expand its scope. A reviewer is fresh
and has not implemented the work; provide the actual diff/files, criteria, context, and
verification commands. Reviewers do not repair the work they review.

## Per-subtask cycle

1. Start the pending task with `[~]`. Dispatch its worker and read the complete native handoff.
   An accepted-but-uncommitted task skips implementation/review unless changes invalidate them.
2. `READY_FOR_REVIEW` routes to independent review. `ESCALATE` routes to main-agent diagnosis;
   repair local implementation issues within approved scope, or return scope decisions to
   the owner. A failed tool/agent invocation is not a verdict.
3. Read the reviewer result. `ESCALATE` requires a targeted repair and another review.
   `PASS` records acceptance and the exact reviewed scope in Notes. This is not a user
   approval gate. Retain `[~]` and `commit pending` until the next step succeeds.
4. The main agent inspects the complete staged diff, stages accepted task files/hunks, and
   commits under the existing approval. Verify history and changed content, then mark `[x]`
   and record the ID. Commit failure leaves the task accepted/commit-pending; do not rerun
   its worker or continue dependent tasks. True no-ops are documented without empty commits.
5. Include progress records in the next task or final verification-record commit. Preserve
   interruptions, resolved errors, and deviations in Notes/Attempts without new state files.

Do not impose arbitrary rework-attempt/time budgets. Report genuine external blockers and
respect user stops, platform limits, and subprocess safety timeouts. Preserve the checkpoint
on interruption. Ordinary reviewed commits do not require repeated user approval.

## Integrated verification and return

After all subtasks are accepted and committed (or documented no-ops), run the agreed final
Verification commands. Obtain an independent final review of the entire task diff from the
recorded starting commit to current HEAD, plus remaining task-owned changes. A clean working
tree is not the full task diff. Separate pre-existing changes using the recorded baseline.

Repair implementation findings within scope and recheck affected results; send requirement
changes back to the owner. Record actual commands, results, final-review outcome, limitations,
and deferred items in Verification. Do not mark the workflow complete merely because tests
passed or all checkboxes are checked.

Return the plan path, verified task commits, test results, final review, and blockers to
`enter-workflow`. Keep its checkpoint active. It owns final branch approval, merge/keep,
wiki/context closure, and reporting. Do not push, merge, or start another lifecycle here.
