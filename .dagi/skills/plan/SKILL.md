---
name: plan
description: Full planning lifecycle — creates a plan file, explores codebase, writes implementation plan, gets approval, and sets the active plan. Invoke via /plan or chained from deliver/grilling.
triggers: /plan, plan this, create a plan
---

# plan

This skill owns the planning phase: creating a plan scaffold, exploring the
codebase, writing the implementation plan, and getting user approval.
When invoked from `deliver`, it returns control to `deliver` on exit. Standalone
`/plan` is fully supported.

## Direct invocation

`/plan` can be invoked directly when requirements are already clear (skipping
`grilling`). When chained from `grilling`, the conversation context from the
interrogation is already available — no re-gathering needed.

## Process

### Step 1 — Create Plan Scaffold

Call `create_plan(task_summary)` where `task_summary` is a short kebab-case slug
derived from the task description (e.g. `"fix-login-bug"`).

This creates a `.dagi/plans/plan_{timestamp}/plan.md` with the standard template.

### Step 2 — Create Git Branch

Use bash to create and check out a task branch:
```
git checkout -b dagi/{task_summary}
```
If not in a git repo or the branch already exists, continue without branching.

### Step 3 — Switch to Advanced Model (optional)

If an advanced model is configured, call `switch_model(tier="plan")` to use
the stronger model for planning. This is optional — if no advanced model is
configured, continue with the current model.

### Step 4 — Generate Spec

Invoke `skill("to-spec")`. This synthesizes the conversation context into a spec
(Problem Statement, Solution, key implementation decisions, testing approach, out of
scope) and saves it to `.dagi/plans/<plan_dir>/spec.md`.

### Step 5 — Explore Codebase

Call `explore_files(...)` with a task informed by the spec's implementation and
testing decisions. The subagent maps relevant files, architecture, and patterns.
Read its handoff when it returns.

### Step 6 — Write Implementation Plan

Write `plan.md` in the plan directory. Use the plan format:
- **Objective and Acceptance** — what the delivery achieves and how it will be verified
- **Scope and Decisions** — what is in scope, what is not, key decisions
- **Workspace** — branch name, expected repository state
- **Subtasks** — each with status marker, goal, requirements, acceptance criteria, tests
- **Context/Approach/Notes** — findings, traps, architectural constraints
- **Verification** — end-to-end verification commands and criteria

### Step 7 — Show and Approve

1. Call `show_plan` to render the plan.
2. Call `ask_user("Approve this plan? Type [approve] to proceed, describe changes
   to modify, or [cancel] to abort.")`
   - **approve** → proceed to Step 8
   - **modify** → edit plan.md, go back to Step 7
   - **cancel** → stop and inform the user

### Step 8 — Set Active Plan

Call `set_active_plan(path)` with the plan file path to associate it with this
session.

### Step 9 — Switch Back to Default Model

If you switched models in Step 3, call `switch_model(tier="default")` to return
to the normal model.

### Step 10 — Return control

If invoked from `deliver`: return control to `deliver`. It will review the plan and
begin execution.

If invoked standalone: report the plan is ready and suggest `/deliver` or
`/dagi-execute` to begin implementation.
