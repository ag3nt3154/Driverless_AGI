---
name: plan
description: Full planning lifecycle — enters plan mode, generates spec from conversation, explores codebase, writes implementation plan, gets approval, exits plan mode. Invoke directly via /plan or chained from grilling.
triggers: /plan, plan this, create a plan
---

# plan

This skill owns the planning phase: entering plan mode, generating a spec,
exploring the codebase, writing the implementation plan, and getting approval.

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
branch, restricts tools to read-only plus plan-file write, and switches to the
advanced model.

### Step 2 — Generate Spec

Invoke `skill("to-spec")`. This synthesizes the conversation context into a spec
(Problem Statement, Solution, User Stories, Implementation Decisions, Testing
Decisions, Out of Scope) and saves it to `.dagi/plans/<plan_dir>/spec.md`.

Wait for the user to confirm the test seams before proceeding.

### Step 3 — Explore Codebase

Call `spawn_explore_files_subagent(...)` with a task informed by the spec's
Implementation Decisions and Testing Decisions sections. The subagent maps
relevant files, architecture, and patterns. Read its handoff when it returns.

### Step 4 — Write Implementation Plan

Write `plan.md` in the plan directory. Use the current plan format:

- **Context** — why this change is needed
- **Approach** — high-level strategy and key decisions
- **Files to Modify** — exact paths
- **Subtasks** — each with:
  - `### Subtask N: [ ] <name>` (status marker in heading)
  - **Goal:** one sentence
  - **Requirements:** bulleted list
  - **Acceptance Criteria:** bulleted list
  - **Test snippets:** key assertions and approach hints (not full test code — the
    main agent expands these into full test files at execution time)
  - Each subtask's execution protocol: write tests → worker implements → review
    grades
- **Notes** — findings from exploration, traps to avoid
- **Verification** — how to verify end-to-end

### Step 5 — Show and Approve

1. Call `show_plan` to render the plan.
2. Call `ask_user("Approve this plan? Type [approve] to proceed, describe changes
   to modify, or [cancel] to abort.")`
   - **approve** → proceed to Step 6
   - **modify** → edit plan.md, go back to Step 5
   - **cancel** → call `exit_plan_mode`, stop

### Step 6 — Exit Plan Mode

Call `exit_plan_mode(summary)` to restore full tools.

### Step 7 — Chain to Execution

Invoke `skill("dagi-execute")` or tell the user: "Plan approved and saved. Invoke
`dagi-execute` to begin implementation."
