---
name: deliver
description: Execute an approved plan with per-task review and integrated verification; return results to enter-workflow.
triggers: /deliver, deliver this, implement this, build this
---

# deliver

This skill is the execution and verification stage owned by `enter-workflow`.
It runs work, per-task review, and integrated verification without a fixed attempt count
or time budget. The main agent reads every subagent handoff before deciding the next step.

## When to invoke

When invoked by `enter-workflow`, run the stage below and return its result to that owner.
When invoked directly via `/deliver`, invoke `skill("enter-workflow")` once with delivery
intent. The owner prepares or reuses the approved plan and calls this execution stage.
Do not route back to the owner again when already running as its stage.
Use `write-plan` to write a plan without execution; this skill does not own planning.

## Routing overview

```
enter-workflow -> deliver -> check approved active plan and execution authority
        -> worker with do-TDD instructions -> ALWAYS read handoff
             READY_FOR_REVIEW -> reviewer -> ALWAYS read handoff
                 PASS -> update accepted task, main agent commits scoped changes
                 ESCALATE -> repair locally or return planning blocker to owner
             ESCALATE -> resolve implementation blocker or return scope decision to owner
        -> integrated verification and general final review
        -> return verification result to enter-workflow for branch finishing and closure
```

## Phase 1 — Orient

Only the main agent orchestrates workers and reviewers. The enclosing owner handles
planning, approval, and association.

Run the checks below in order. Reconcile recoverable evidence before returning a blocker.
Unresolved authorization or conflicting evidence blocks dependent work.
Do not attach a different plan, invoke writers, or restart grilling here.

### 1. Identify the task

Call `check_active_plan()` to get the associated plan path. If no plan is associated,
recover the exact task and known artifact path from the owner's checkpoint/conversation.
A matching slug or newest plan alone is not association evidence. If identity cannot be
recovered unambiguously, return a blocker to the owner.

### 2. Check the branch

Read the plan's `## Workspace` section for the recorded branch name. Run
`git branch --show-current` and verify it matches. `dagi/<task>` is the default;
honor an explicitly approved project override recorded by the owner. Verify the recorded
artifact directory instead of re-deriving it from the prefix. Unexplained mismatch blocks
execution; an already confirmed merge returns to the owner for closure.

### 3. Check the artifacts

Verify that both `spec.md` and `plan.md` exist in the task's wiki folder
(`wiki/tasks/YYYY-MM-DD_<task>/`). Either file missing → stop and report.

### 4. Check authorization and document commit separately

Recover actual user approval from conversation/checkpoint evidence: exact artifact scope,
execution permission, and authority for main-agent reviewed subtask commits. Planning-only
approval does not authorize execution. A plan, label, review PASS, or matching commit
subject proves no user permission. Return unresolved or conflicting authority to the owner.
Then inspect Git history and the actual committed spec/plan contents against the approved
versions. The conventional subject helps locate the commit but is insufficient evidence.
Confirm the owner recorded the approval (scope and commit authority) before implementation.
Missing gates return to the owner; do not request routine per-subtask approval.

### 5. Validate plan format

Parse the plan with `parse_subtask_statuses()`. Verify:
- At least one `### Subtask N:` heading exists.
- Each subtask contains `**Goal:**` and `**Acceptance Criteria:**`.
- The plan header contains `**Goal:**` and `**Spec:**`.

If the plan is malformed or truncated (e.g. planning was interrupted), stop and report.

### 6. Reconcile subtask progress

Read markers together with plan Notes, review acceptance, history and committed diffs:
- `[x]`: verify the recorded commit and accepted scope, or a documented valid no-op.
- `[~]`/`[!]`: identify implementation, review, or accepted/commit-pending work from Notes.
- `[ ]`: pending unless accepted/committed evidence proves the marker is stale.

If an interrupted commit actually succeeded, verify its task-owned contents and reconcile
the marker/ID without rerunning the worker or committing again. If review passed but no
commit exists, resume only the commit step. Correct stale progress when evidence is clear;
return only unresolved contradictions to the owner. Never infer acceptance from a matching
commit subject alone. A documented no-op needs verified existing behavior and review, not
an empty commit.

### After verification

If all checks pass: proceed to Phase 2 with pending subtasks. Resume accepted-but-
uncommitted subtasks at their commit after inspecting Git history, not by rerunning the
worker. If all subtasks are complete and verification is the recorded next action,
continue at Phase 3. If only branch finishing/closure remains, return to the owner
without repeating implementation or already valid verification.

## Phase 2 — Execute with per-task review

All subagents must not launch subagents.

For each pending or accepted-but-uncommitted subtask (in order), use its recorded evidence.
An already accepted subtask resumes at step 2c's commit after Git-history inspection;
do not repeat its worker or review unless changes invalidate acceptance.

1. Load `skill("do-tdd")` once for this delivery and retain its instructions.
   Call `run_worker(subtask_name, custom_instructions=...)`, including the full TDD
   instructions, the approved behavior, and any repair context. Workers lack the skill
   tool; a skill name alone is insufficient. Supply the instructions on repair calls too.
   Read the handoff and its red/green evidence or stated test limitation — always.

2. If `READY_FOR_REVIEW`:
   a. Call `review_work` with:
      - `material`: the worker handoff path
      - `passing_criteria`: the subtask's acceptance criteria
      - `context`: plan context and subtask goal
      - `verification`: relevant test commands from the subtask
   b. Read the reviewer handoff — always.
   c. **PASS**: Record review accepted / commit pending and review evidence in Notes;
      retain `[~]` (use `update_task_status(task=N, status="in_progress")` as needed).
      The main agent stages only accepted task changes and progress records, inspects
      the entire staged diff, and commits under the existing scoped authority. Follow
      the owner's Git rules; workers never commit and no per-subtask approval is needed.
      Verify the commit and its task-owned diff, then call
      `update_task_status(task=N, status="complete")` and record its ID. A valid reviewed
      no-op records its evidence and completes without manufacturing an empty commit.
      Commit failure retains accepted/commit-pending Notes and `[~]`; inspect history
      before retrying. Do not repeat accepted work merely because the marker lagged.
      Put post-commit progress updates in the next task commit or final verification-record
      commit. Keep the final record commit's own ID in the conversation/Git checkpoint,
      avoiding an infinite chain of commits to record their own IDs.
   d. **ESCALATE**: Diagnose the findings and assign a targeted implementation repair,
      then repeat from step 1. If the approved requirements or plan need revision,
      return that blocker to the owner instead. Worker debugging has no fixed attempt count.

3. If `ESCALATE` from the worker: resolve implementation blockers locally. Return
   requirement, plan, or scope decisions to `enter-workflow` for resolution.

4. Record concise resolved errors in the plan. Link full diagnostics by handoff path.

## Phase 3 — Integrated verification and final review

After all subtasks are accepted and their commits verified (or documented as no-op):

1. Run the full verification suite defined in the plan's Verification section.

2. Call `review_work` with:
   - `material`: the full task diff from the recorded starting commit to current task HEAD,
     including any remaining task changes; a clean working-tree diff is not the task diff
   - `passing_criteria`: the plan's Verification criteria and agreed-on non-regression requirements
   - `context`: the complete delivery summary

3. Read the final review handoff — always.
   - **PASS**: proceed to Phase 4.
   - **ESCALATE**: assign implementation repair or return a scope blocker to the owner.

## Phase 4 — Return delivery result

1. Write a delivery summary to the plan's Verification section: what was built, what
   tests pass, any deferred items, and the final review outcome.

2. Return the plan path, implementation status, test commands/results, final review
   outcome, and unresolved or deferred items to `enter-workflow`.

3. Leave the plan associated. The owner invokes `merging-git-branch`, checks project
   context, and detaches after successful closure. Do not merge or call another lifecycle
   skill as part of this return.

## Constraints

- The main agent alone edits shared plan progress (`update_task_status`, plan notes).
  Workers receive assignments; they do not edit the plan, stage files, or commit.
- No fixed attempt count, implementation budget, or time limit on any phase.
  Unresolved blockers or invalid assignments return a handoff; the main agent decides.
- User stop is always respected. If the user stops mid-delivery, the plan remains
  associated for resumption via `deliver`.
- Standalone `write-plan` writes the artifact and returns without delivery.
- Requirement or scope changes return to the owner for the affected planning/approval
  stage. Local implementation repairs remain inside the execution/review loop.

## Plan template

Load the canonical delivery-format reference from
`../write-plan/references/plan-template.md`, resolving that path relative to this
skill file's directory. The writer owns the plan's structure; delivery fills runtime
sections such as Overall Status, Notes, Attempts and Resolutions, Verification, and
Next Action. Retain parser headings (`### Subtask N:`, `**Goal:**`,
`**Requirements:**`, `**Acceptance Criteria:**`, `#### Tests`). Record review accepted /
commit pending in Notes until the commit is verified, then record its commit ID and
set the marker to `[x]`.

## Review assignments — documentation

A **review assignment** includes:
- `material`: what to evaluate (file paths, diff spec, or inline text)
- `passing_criteria`: explicit checkable conditions for PASS
- `context`: background and task goal
- `verification`: commands to run

**PASS** means all criteria are met; non-blocking observations are noted.
**ESCALATE** means at least one criterion fails or a credible blocker exists.

Process-execution status (`ok`, `error`, `timeout`) is separate from review outcome
(`PASS`, `ESCALATE`). A tool that returns an error result has not produced a review.

**Safety timeouts** on subprocess execution are separate from implementation budgets
(which do not exist in this workflow). Timeouts protect the host from runaway
processes; they do not cap the number of rework cycles.
