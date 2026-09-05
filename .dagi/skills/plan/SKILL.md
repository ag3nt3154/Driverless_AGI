---
name: plan
description: Full planning lifecycle — enters plan mode, generates spec from conversation, explores codebase, writes implementation plan, gets approval, exits plan mode. Invoke directly via /plan or chained from deliver/grilling.
triggers: /plan, plan this, create a plan
---

# plan

This skill owns the planning phase: entering plan mode, generating a spec,
exploring the codebase, writing the implementation plan, and getting approval.
When invoked from `deliver`, it returns control to `deliver` on exit. Standalone
`/plan` is fully supported.

## Direct invocation

`/plan` can be invoked directly when requirements are already clear (skipping
`grilling`). When chained from `grilling`, the conversation context from the
interrogation is already available — no re-gathering needed.

## Process

### Step 1 — Enter Plan Mode

Call `enter_plan_mode(mode, task_summary)` where:
- `mode`: `"interactive"` when invoked by the user; `"autonomous"` when DAGI
  initiates internally
- `task_summary`: a short kebab-case slug derived from the task description
  (e.g. `"fix-login-bug"`)

This is a pure infrastructure call — it enters plan-mode state, creates a git
branch, restricts tools to read-only plus plan-file/spec-file write, and switches
to the advanced model.

### Step 2 — Generate Spec

Invoke `skill("to-spec")`. This synthesizes the conversation context into a spec
(Problem Statement, Solution, key implementation decisions, testing approach, out of
scope) and saves it to `.dagi/plans/<plan_dir>/spec.md`.

### Step 3 — Explore Codebase

Call `explore_files(...)` with a task informed by the spec's implementation and
testing decisions. The subagent maps relevant files, architecture, and patterns.
Read its handoff when it returns.

### Step 4 — Write Implementation Plan

Write `plan.md` in the plan directory. Use the plan format defined in the `deliver`
skill's plan template section:
- **Objective and Acceptance** — what the delivery achieves and how it will be verified
- **Scope and Decisions** — what is in scope, what is not, key decisions
- **Workspace** — branch name, expected repository state
- **Subtasks** — each with status marker, goal, requirements, acceptance criteria, tests
- **Context/Approach/Notes** — findings, traps, architectural constraints
- **Verification** — end-to-end verification commands and criteria

### Step 5 — Show and Approve

1. Call `show_plan` to render the plan.
2. Call `ask_user("Approve this plan? Type [approve] to proceed, describe changes
   to modify, or [cancel] to abort.")`
   - **approve** → proceed to Step 6
   - **modify** → edit plan.md, go back to Step 5
   - **cancel** → call `exit_plan_mode(summary="cancelled")`, stop

### Step 6 — Exit Plan Mode

Call `exit_plan_mode(summary)` with a one-sentence summary of what the plan covers.
Full tools are restored and the plan is set as the active plan automatically.

### Step 7 — Return control

If invoked from `deliver`: return control to `deliver`. It will review the plan and
begin execution.

If invoked standalone: report the plan is ready and suggest `/deliver` or
`/dagi-execute` to begin implementation.
