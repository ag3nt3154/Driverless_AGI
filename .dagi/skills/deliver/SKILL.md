---
name: deliver
description: Full delivery lifecycle — grilling, planning with review, execution with per-task review, integrated verification, final review, and explicit detach. Invoke via /deliver for any non-trivial implementation request.
triggers: /deliver, deliver this, implement this, build this
---

# deliver

This skill owns the complete delivery lifecycle: from clarifying intent through final
integrated verification. It orchestrates grilling, planning, work, review, and verification
without a fixed attempt count or time budget. The main agent reads every subagent handoff
before deciding the next step.

## When to invoke

Use `/deliver` for any non-trivial implementation request. Use `/plan` alone when you only
need a plan without executing it. Use `dagi-execute` when a plan already exists and is
associated.

## Routing overview

```
deliver -> check active plan / inspect request
        -> grilling when intent remains unresolved
        -> plan -> general reviewer -> revise until satisfactory
        -> agreed execution authority -> set active plan
        -> worker -> ALWAYS read handoff
             READY_FOR_REVIEW -> reviewer -> ALWAYS read handoff
                 PASS -> update accepted task, incorporate observations
                 ESCALATE -> diagnose findings, assign repair or revise plan
             ESCALATE -> resolve blocker or revise plan; ask user only if needed
        -> integrated verification and general final review
        -> report outcome, record final state, explicitly detach if finished
```

## Phase 1 — Orient

1. Call `check_active_plan()`.
   - If a plan is already associated and matches the request, jump to Phase 4.
   - If a different plan is associated, confirm with the user before overriding.
   - If no plan exists, proceed to Phase 2.

## Phase 2 — Clarify (grilling)

If the request has unresolved ambiguity — missing requirements, unclear scope, or
conflicting constraints — invoke `skill("grilling")`. Grilling returns control here
when done; it does not launch implementation. Do not re-grill aspects already resolved
in the current conversation.

When intent is clear, proceed directly to Phase 3.

## Phase 3 — Plan and plan review

1. Invoke `skill("plan")`. The plan skill enters plan mode, generates a spec, explores
   the codebase, writes the implementation plan, gets user approval, and exits plan mode.
   Plan returns control here on exit — it does not launch execution.

2. After plan exits, call `check_active_plan()` to confirm the plan is associated.

3. Call `review_work` with:
   - `material`: the plan file path
   - `passing_criteria`: completeness (all subtasks have criteria), testability
     (acceptance criteria are checkable), consistency (approach matches requirements),
     and absence of obvious implementation traps
   - `context`: the request and key decisions from grilling

4. Read the review handoff.
   - **PASS**: proceed to Phase 4.
   - **ESCALATE**: use `edit` to revise the existing plan file in place (do NOT invoke
     `enter_plan_mode` — that creates a new scaffold and branch, orphaning the current
     association). Address each blocking finding, then repeat from step 3. Ask the user
     only if a finding requires a decision outside the original scope.

## Phase 4 — Execute with per-task review

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
   d. **ESCALATE**: Diagnose the findings. Either: assign a targeted repair to a new
      worker call, or use `edit` to revise the subtask in the existing plan file in place
      (do NOT invoke `enter_plan_mode` — that creates a new scaffold, not a revision).
      Then repeat from step 1. Worker debugging continues locally — no fixed attempt count.

3. If `ESCALATE` from the worker: resolve the blocker or revise the plan. Ask the user
   only when a decision is needed that is outside the agreed scope.

4. Record concise resolved errors in the plan. Link full diagnostics by handoff path.

## Phase 5 — Integrated verification and final review

After all subtasks are accepted:

1. Run the full verification suite defined in the plan's Verification section.

2. Call `review_work` with:
   - `material`: the git diff or key changed files
   - `passing_criteria`: the plan's Verification criteria and agreed-on non-regression requirements
   - `context`: the complete delivery summary

3. Read the final review handoff — always.
   - **PASS**: proceed to Phase 6.
   - **ESCALATE**: treat as a new blocker; assign repair or ask user for scope decision.

## Phase 6 — Report and detach

1. Write a delivery summary to the plan's Verification section: what was built, what
   tests pass, any deferred items, and the final review outcome.

2. Present the outcome to the user.

3. Call `set_active_plan(null)` to detach explicitly. The plan document is preserved on
   disk — reference it by path if needed later.

## Constraints

- The main agent alone edits shared plan progress (`update_task_status`, plan notes).
  Workers receive assignments; they do not edit the plan.
- No fixed attempt count, implementation budget, or time limit on any phase.
  Unresolved blockers or invalid assignments return a handoff; the main agent decides.
- User stop is always respected. If the user stops mid-delivery, the plan remains
  associated for resumption via `dagi-execute`.
- Standalone `/plan` remains fully usable without `/deliver`.
- Grilling and plan return to this skill's control flow — they do not recursively
  launch execution or call deliver.

## Plan template

Use this structure when writing `plan.md` in Phase 3. Retain all headings used by
the worker-extraction parser (`### Subtask N:`, `**Goal:**`, `**Requirements:**`,
`**Acceptance Criteria:**`, `#### Tests`).

```markdown
# Plan: <task-summary>

## Objective and Acceptance
What this delivery achieves and how success will be verified end-to-end.

## Scope and Decisions
What is in scope, what is explicitly out of scope, and key decisions made
during grilling/planning (link to spec.md if generated).

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
(The plan skill expands test snippets into full files; workers run existing tests.)

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
