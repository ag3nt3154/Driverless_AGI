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
        -> worker -> ALWAYS read handoff
             READY_FOR_REVIEW -> reviewer -> ALWAYS read handoff
                 PASS -> update accepted task, incorporate observations
                 ESCALATE -> repair locally or return planning blocker to owner
             ESCALATE -> resolve implementation blocker or return scope decision to owner
        -> integrated verification and general final review
        -> return verification result to enter-workflow for closure
```

## Phase 1 — Orient

Only the main agent orchestrates workers and reviewers. The enclosing owner handles
the overall wiki lookup, planning, approval, and association.

Call `check_active_plan()`. Require a matching plan, correct branch, user approval,
execution authorization, and an accepted plan review. Missing or conflicting evidence
returns a blocker to `enter-workflow`; do not attach a different plan, invoke writers,
or restart grilling here. Proceed to Phase 2 only when the handoff is ready.

## Phase 2 — Execute with per-task review

Before the first worker, verify successful approval wiki-add evidence in the plan notes
or prior handoff. If missing, return to the owner for its required approval wiki-add;
do not start a worker. Do not assume approval itself saved knowledge.
All subagents must not launch subagents. Read their `Wiki requests` and discretionarily
initiate queries/adds for substantial findings, bugs or fixes. No default per-subtask calls.

For each pending subtask in the plan (in order):

1. Call `run_worker(subtask_name)`. Read the handoff — always.

2. If `READY_FOR_REVIEW`:
   a. Call `review_work` with:
      - `material`: the worker handoff path
      - `passing_criteria`: the subtask's acceptance criteria
      - `context`: plan context and subtask goal
      - `verification`: relevant test commands from the subtask
   b. Read the reviewer handoff — always.
   c. **PASS**: Call `update_task_status(task=N, status="complete")`. Incorporate any
      non-blocking observations into the plan's Notes section.
   d. **ESCALATE**: Diagnose the findings and assign a targeted implementation repair,
      then repeat from step 1. If the approved requirements or plan need revision,
      return that blocker to the owner instead. Worker debugging has no fixed attempt count.

3. If `ESCALATE` from the worker: resolve implementation blockers locally. Return
   requirement, plan, or scope decisions to `enter-workflow` for resolution.

4. Record concise resolved errors in the plan. Link full diagnostics by handoff path.

## Phase 3 — Integrated verification and final review

After all subtasks are accepted:

1. Run the full verification suite defined in the plan's Verification section.

2. Call `review_work` with:
   - `material`: the git diff or key changed files
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

3. Leave the plan associated. The owner records completion through `wiki-add`, checks
   project context, presents the outcome, and detaches. Do not merge or call another
   lifecycle skill as part of this return.

## Constraints

- The main agent alone edits shared plan progress (`update_task_status`, plan notes).
  Workers receive assignments; they do not edit the plan.
- No fixed attempt count, implementation budget, or time limit on any phase.
  Unresolved blockers or invalid assignments return a handoff; the main agent decides.
  Required wiki operations are the exception: one retry, then the failure policy above.
- `wiki-refresh` runs only on explicit user request, directly in the main agent.
- Personal memory access requires an explicit user request; project wiki never falls back to it.
- User stop is always respected. If the user stops mid-delivery, the plan remains
  associated for resumption via `deliver`.
- Standalone `write-plan` writes the artifact and returns without delivery.
- Requirement or scope changes return to the owner for the affected planning/approval
  stage. Local implementation repairs remain inside the execution/review loop.

## Plan template

This is the existing delivery-format reference, not a planning stage. Retain headings used by
the worker-extraction parser (`### Subtask N:`, `**Goal:**`, `**Requirements:**`,
`**Acceptance Criteria:**`, `#### Tests`).

```markdown
# Plan: <task-summary>

## Objective and Acceptance
What this delivery achieves and how success will be verified end-to-end.

## Scope and Decisions
What is in scope, what is explicitly out of scope, and key decisions made
during grill-me/planning (link to spec.md if generated).

## Workspace
- **Branch:** `<branch-name>`
- **Repository state:** describe expected state (e.g. clean main, feature branch)

## Overall Status
Pending / In Progress / Verification / Complete / Blocked

## Context
Why this change is needed and relevant background.

## Approach
High-level strategy and key design choices.

## Files to Modify
- `path/to/file.py` — reason

## Subtasks

### Subtask 1: [ ] <name>
**Goal:** One sentence.
**Requirements:**
- Bulleted list of what must be true.
**Acceptance Criteria:**
- Bulleted list of checkable conditions.
#### Tests
Test file paths and one-line description of what each verifies.
(Workers use the supplied tests and verification instructions.)

## Notes
Findings from exploration, traps to avoid, architectural constraints.

## Open Issues
Unresolved questions or blockers not yet addressed.

## Attempts and Resolutions
One block per rework cycle:
- **Task N, attempt N:** blocker summary → resolution (or link to handoff)

## Verification
End-to-end verification commands and expected outcomes.

## Next Action
One sentence: what happens next after reading this plan.
```

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
