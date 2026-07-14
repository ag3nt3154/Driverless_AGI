---
name: plan-work-review
description: Full planning and execution lifecycle for complex tasks — enters plan mode, delegates codebase exploration to an explore subagent, grills the user on requirements, writes and approves a plan, then executes it via worker and review subagents with retry logic.
triggers: plan, /plan, /plan-work-review, execute plan, start plan work review, run plan work review cycle
---

## Plan-Work-Review

This skill owns the full lifecycle for complex tasks: planning, approval, and execution. Follow both phases in order.

---

## Phase 1 — Planning

### Step 1 — Enter Plan Mode
Call `enter_plan_mode(mode="interactive", task_summary="<short-kebab-case-slug>")` if this skill was invoked by the user (slash command or explicit request). Call `enter_plan_mode(mode="autonomous", task_summary="<short-kebab-case-slug>")` if DAGI initiated this internally. `task_summary` should be a short kebab-case slug capturing the task (e.g. `"fix-login-bug"`) — it seeds the plan title and names the git branch DAGI automatically creates and checks out for this task. If the tool result's `**Branch:**` line shows "no git repository detected", DAGI has no git workflow for this task — proceed with planning normally, just skip all git_* steps below.

### Step 2 — Grill (interactive mode only)
**This step runs before any exploration or planning.** Invoke `skill("grill-me")` immediately after entering plan mode. The skill will stress-test the requirements, surface hidden assumptions, and force concrete decisions. Answer questions using any knowledge already in context — do NOT spawn the explore subagent yet.

**Do not exit this step early.** A user saying "ready", "proceed", or "let's go" is not by itself a signal to stop — grill-me ends its own interrogation per its Phase 3 closing criteria (every decision-tree branch resolved, a closing summary produced), not on user impatience. Only treat an explicit override ("skip the grilling", "stop questioning me", "cancel") as license to cut the interrogation short. Otherwise, keep answering grill-me's questions until it produces its Phase 3 closing summary, then proceed to Step 3.

### Step 3 — Explore via Subagent
Now that requirements are clear from grilling, delegate targeted codebase discovery to the explore subagent — do not use `read`, `grep`, or `find` directly for exploration.

Call `spawn_explore_files_subagent(...)` with:
- `task`: a precise description of what to discover, informed by what grilling revealed (e.g. "Map all tool registration paths and explain how tools are loaded at startup. Identify files that will need to change for X.")
- `handoff_file`: leave this unset — the tool generates the path automatically

The subagent's job is to describe the codebase, not to plan — its handoff contains **Summary**, **Citations**, and **Notes** sections only (see `.dagi/subagents/explore_files/prompt.md`). If its output reads like a plan (proposed steps, ordered implementation, architecture decisions), that is out of scope for it — treat any such content as raw findings, not as the plan itself, and do the actual planning yourself in Step 4.

Once the tool returns, read the handoff file it reports. Use its **Summary**, **Citations**, and **Notes** to inform the plan you write yourself in Step 4.

### Step 4 — Write the Plan
Write the plan document to the plan file. Use this structure:

```markdown
# Plan — <task title>

## Context
Why this change is needed and what outcome it produces.

## Approach
High-level strategy and key decisions.

## Files to Modify
- path/to/file.py — what changes

## Subtasks

### Subtask 1: [ ] <name>
**Goal:** One sentence.
**Requirements:**
- ...
**Acceptance Criteria:**
- ...
#### Tests
<!-- filled in by main agent before spawning worker -->

> **Status marker format:** Each subtask heading must include a status marker immediately
> after the colon: `### Subtask N: [marker] name`. Valid markers:
> `[ ]` pending · `[~]` in-progress · `[x]` complete · `[!]` failed
```

## Notes
Salient findings, traps to avoid, decisions made during execution.

## Verification
How to verify the full implementation end-to-end.

## Execution Protocol

> **MANDATORY — read this section before implementing any subtask.**
>
> Do NOT implement subtasks directly. Follow this cycle for each pending subtask:
>
> 1. **Write tests** for the subtask in `.dagi/plans/<plan_dir>/tests/`
> 2. **Spawn a worker subagent** via `spawn_worker_subagent(subtask_name=..., custom_instructions=...)`
> 3. **Spawn a review subagent** via `spawn_review_subagent(subtask_name=..., worker_handoff_path=..., unit_test_paths=...)`
> 4. **Evaluate** the review verdict — PASS marks `[x]`, FAIL retries (max 2 attempts), ESCALATED re-spawns free of charge
>
> If you find yourself editing implementation files directly, STOP — you are
> violating this protocol. Re-read this section and delegate to subagents.
```

### Step 5 — Show and Approve
1. Call `show_plan` to render the plan.
2. In interactive mode: call `ask_user("Approve this plan? Type [approve] to proceed, describe changes to modify, or [cancel] to abort.")`
   - **approve** → call `exit_plan_mode`, proceed to Phase 2
   - **modify** → edit the plan file to incorporate feedback, go back to Step 5
   - **cancel** → call `exit_plan_mode`, stop — do NOT proceed to execution
3. In autonomous mode: `show_plan` auto-approves — call `exit_plan_mode`, proceed to Phase 2.

---

## Phase 2 — Work-Review Cycle

Execute this cycle for each `[ ] pending` subtask in the plan. Delegate all execution to worker subagents and all evaluation to review subagents.

### Step 1 — Write Tests
Before spawning the worker, write the unit/integration test file(s) for this subtask:
- Read the subtask's **Acceptance Criteria** and translate them into concrete test assertions
- Write all test files to `.dagi/plans/{plan_ts}/tests/` — derive `{plan_ts}` from the `plan_file` path you received when entering plan mode (e.g. if plan_file is `.dagi/plans/plan_20260606_120000/plan.md`, tests go in `.dagi/plans/plan_20260606_120000/tests/`). Create the directory if it does not exist.
- Edit `plan.md` to fill in the subtask's `#### Tests` subsection with the test file path(s) and a one-line description of what each test verifies
- Do NOT pass test paths to the worker — tests are a hidden oracle for the review stage only

### Step 2 — Spawn Worker Subagent
Before spawning, edit `plan.md` to change the subtask heading marker from `[ ]` to `[~]`
(in-progress). This updates the TUI sidebar immediately so the user can see work has begun.

> **Note:** `[~]` persists if execution is interrupted. On resume, the user or agent must
> inspect the subtask to determine whether to retry or mark complete.

Call `spawn_worker_subagent(...)` with:
- `subtask_name`: the subtask name exactly as it appears in `plan.md` (e.g. `"Subtask 1: Add login endpoint"`)
- `custom_instructions` (optional): any guidance, traps to avoid, or context from prior failed attempts

The tool automatically injects the plan context (Context, Approach, Notes sections) and the subtask details into the subagent's context — do NOT duplicate this manually.

When the tool returns, it reports the path to the worker's handoff file. Keep this path — you need it for Step 3.

### Step 3 — Spawn Review Subagent
Call `spawn_review_subagent(...)` with:
- `subtask_name`: the subtask name exactly as it appears in `plan.md`
- `worker_handoff_path`: path to the worker's handoff report from Step 2
- `unit_test_paths`: list of paths to test files written in Step 1
- `custom_instructions` (optional): any additional evaluation guidance

The tool automatically injects plan context and the subtask block (including the Tests section) — do NOT duplicate this manually.

When the tool returns, it reports the path to the review report. Read it in Step 4.

### Step 4 — Evaluate and Decide
Read the review report. Pass/fail is determined by the review subagent's verdict — not your own judgment.

**If ESCALATED:** The worker or review subagent raised a blocking question instead of producing a
handoff/review report (the tool result starts with `[worker escalated]` or `[review escalated]`).
- Read the question and context in full.
- Decide the answer yourself if you can — you have full repo access and the plan/conversation
  context the subagent doesn't. Only call `ask_user` if it's a genuine judgment call the user must
  make (e.g. a product decision, not a technical detail you can look up or infer).
- Re-spawn the **same subagent type** for the **same subtask**, passing the answer via
  `custom_instructions` (e.g. `"custom_instructions": "Answering your escalation: use bcrypt, not argon2, per existing auth.py conventions."`).
- **This does not consume a retry attempt.** Escalations are free — do not increment your attempt
  count for this subtask. Go back to Step 2 (or Step 3, if it was the review subagent that
  escalated) with the same attempt number as before.

**If PASS:**
- Edit `plan.md` and mark the subtask `[x] complete`
- If this task has a git branch (see Step 1 — skip this bullet if none was created): call `git_add` with the list of files this subtask touched, then `git_commit` with a message summarizing the subtask (e.g. `"Subtask 2: Add login endpoint"`). Do this every time a subtask passes review — never batch commits across subtasks.
- Append a PASS entry to `cycle_log.md` in the plan subfolder
- Update the `## Notes` section of `plan.md` with salient findings from the review
- Proceed to the next subtask

**If FAIL:**
- Append a FAIL entry to `cycle_log.md` with: verdict, artifact file names, issue summary, action taken
- Update `## Notes` in `plan.md` with salient findings
- Decide retry strategy:
  - **Worker fell into a trap** (plan is sound, execution failed): retry with augmented custom instructions
  - **Plan is flawed** (subtask requirements or approach are wrong): edit the subtask in `plan.md`, then retry

**If 2 attempts are exhausted without PASS** (1 initial attempt + 1 retry — escalations are free
and do not count toward this budget):
- Mark the subtask `[!] failed` in `plan.md`
- Stop the cycle
- Present a structured escalation report:
  - Summary of all attempt handoff/review artifacts (filenames + one-line summary)
  - Your diagnosis of the root cause
  - Proposed solutions or paths forward
- Wait for user guidance before continuing

### Step 5 — Complete the Plan
Once **every** subtask is resolved (all markers are `[x]` or `[!]` — none remain `[ ]` or `[~]`), call `complete_plan()`.

This clears the active plan reference from the loop. After this call:
- Future subagent handoffs route back to `.dagi/handoffs/`
- The TUI plan panel clears
- The plan document is preserved on disk at its original path — reference it by path if needed

Do NOT call `complete_plan()` mid-cycle or before all subtasks are settled.

**After `complete_plan()`, if this task has a git branch:** finish any remaining housekeeping first (e.g. invoke the `update-project-context` skill if the change is significant), then report a summary to the user covering:
- The branch name (from Step 1's `**Branch:**` line)
- Number of commits made and files changed — summarize from `cycle_log.md` (each PASS entry logged there corresponds to one commit), or call `git_log(count=<n>)` to list the commits made on this branch since it was created.
- A reminder that the branch is ready for the user to review and merge manually — DAGI does not merge branches itself.

Do NOT attempt to merge the branch, switch back to `main`, or delete the task branch. Leave it exactly as-is for the user.

---

## cycle_log.md Format

Maintain `cycle_log.md` in the plan subfolder. Append one block per attempt:

```markdown
## Subtask N: <name>
### Attempt N — PASS/FAIL
- Worker: .dagi/handoffs/worker_<id>.md
- Review: .dagi/handoffs/review_<id>.md
- Issue: <one-line summary, or "None">
- Action: <what you did next, or "Subtask complete">
```
