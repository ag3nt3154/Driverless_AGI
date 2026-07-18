---
name: dagi-execute
description: Execute an approved plan via the work-review cycle — main agent writes tests, worker subagent implements, review subagent grades, main agent commits. Handles retry logic, escalation, completion, and branch cleanup.
triggers: /execute, execute plan, start execution
---

# dagi-execute

Execute the approved plan subtask by subtask. Delegate implementation to worker
subagents and evaluation to review subagents. The main agent writes tests and
commits.

## Prerequisites

- A plan file must be active (`config.active_plan_file` is set)
- The plan must have been approved and plan mode exited
- Read the plan file in full before starting

## Per-Subtask Cycle

For each `[ ] pending` subtask in the plan:

### Step 1 — Write Tests

Before spawning the worker, write the test file(s) for this subtask:
- Read the subtask's **Acceptance Criteria** and **Test snippets**
- Expand them into full test files
- Save to `.dagi/plans/{plan_dir}/tests/`
- Edit `plan.md` to fill in the subtask's `#### Tests` subsection with test file
  paths and a one-line description of what each test verifies
- Do NOT pass test paths to the worker — tests are a hidden oracle for review only

### Step 2 — Spawn Worker

Edit `plan.md` to change the subtask heading marker from `[ ]` to `[~]`
(in-progress).

Call `spawn_worker_subagent(subtask_name, custom_instructions)`. The tool
automatically injects plan context and subtask details. Keep the returned handoff
path for Step 3.

### Step 3 — Spawn Review

Call `spawn_review_subagent(subtask_name, worker_handoff_path, unit_test_paths)`.
The tool automatically injects plan context and the subtask block (including
Tests section). Read the returned review report.

### Step 4 — Evaluate and Decide

Pass/fail is determined by the review subagent's verdict — not your own judgment.

**If ESCALATED:** The subagent raised a blocking question (tool result starts with
`[worker escalated]` or `[review escalated]`).
- Read the question in full
- Decide the answer yourself if you can — you have full repo access and
  conversation context the subagent doesn't
- Only call `ask_user` for genuine product decisions
- Re-spawn the same subagent type with the answer via `custom_instructions`
- This does NOT consume a retry attempt — go back to Step 2 or 3

**If PASS:**
- Edit `plan.md` and mark the subtask `[x] complete`
- `git add` the files this subtask touched, then `git commit` with a message
  summarizing the subtask
- Append a PASS entry to `cycle_log.md` in the plan directory
- Update the `## Notes` section of `plan.md` with salient findings
- Proceed to the next subtask

**If FAIL:**
- Append a FAIL entry to `cycle_log.md` with: verdict, artifact file names,
  issue summary, action taken
- Update `## Notes` in `plan.md` with salient findings
- Decide retry strategy:
  - **Worker fell into a trap** (plan is sound): retry with augmented
    custom_instructions
  - **Plan is flawed** (subtask requirements wrong): edit the subtask in plan.md,
    then retry

**If 2 attempts exhausted** (1 initial + 1 retry; escalations free):
- Mark the subtask `[!] failed` in plan.md
- Stop the cycle
- Present structured escalation report:
  - Summary of all attempt handoff/review artifacts
  - Root cause diagnosis
  - Proposed solutions
- Wait for user guidance before continuing

## Completion

Once every subtask is resolved (all markers `[x]` or `[!]`):

1. Call `complete_plan()`
2. Invoke `skill("update-project-context")`
3. Commit context updates
4. If `config.previous_branch` is set, run `git checkout <previous_branch>` to
   return to the branch the user was on before plan mode. If it is `None` (e.g.
   the task started outside a git repo), skip this step and note in the summary
   that no checkout was performed. Do NOT merge, force-push, or delete the task
   branch.
5. Report summary:
   - Branch name
   - Number of commits and files changed
   - Reminder that the branch is ready for user review and merge

## cycle_log.md Format

Maintain `cycle_log.md` in the plan directory. Append one block per attempt:

```
## Subtask N: <name>
### Attempt N — PASS/FAIL
- Worker: .dagi/handoffs/worker_<id>.md
- Review: .dagi/handoffs/review_<id>.md
- Issue: <one-line summary, or "None">
- Action: <what you did next, or "Subtask complete">
```
