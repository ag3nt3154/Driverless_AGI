---
name: plan-work-review
description: Execute the Plan-Work-Review cycle after plan mode exits — spawns worker and review subagents for each pending subtask, retries on failure, and escalates after 3 failed attempts.
triggers: plan, execute plan, start plan work review, run plan work review cycle
---

## Plan-Work-Review Cycle

Every time plan mode exits with a confirmed plan, execute this cycle. Delegate all execution to worker subagents and all evaluation to review subagents.

### For Each `[ ] pending` Subtask

#### Step 1 — Write Tests
Before spawning the worker, write the unit/integration test file(s) for this subtask:
- Read the subtask's **Acceptance Criteria** and translate them into concrete test assertions
- Write the test file(s) to disk
- Edit `plan.md` to fill in the subtask's `#### Tests` subsection with the test file path(s) and a one-line description of what each test verifies
- Do NOT pass test paths to the worker — tests are a hidden oracle for the review stage only

#### Step 2 — Spawn Worker Subagent
Call `spawn_subagent(type="worker", task=...)` with a prompt containing:
- The **Context**, **Architecture/Overview**, and **Notes** sections from `plan.md` (copy verbatim)
- The full subtask block (Goal, Requirements, Acceptance Criteria) — **do NOT include test paths or test file contents**
- Your **custom instructions** — any guidance, traps to avoid, or context from prior failed attempts
- `handoff_file`: path for the handoff report, named `handoff_{attempt}_{subtask_slug}.md` in the plan subfolder
- `plan_subfolder`: absolute path to the plan subfolder

Where `{attempt}` is the 1-based attempt number (01, 02, 03) and `{subtask_slug}` is the subtask name lowercased with spaces replaced by underscores.

#### Step 3 — Spawn Review Subagent
Call `spawn_subagent(type="review", task=...)` with a prompt containing:
- The **Context**, **Architecture/Overview**, and **Notes** sections from `plan.md` (copy verbatim)
- The subtask's **Requirements** and **Acceptance Criteria**
- `handoff_file`: path to the worker's handoff report
- `unit_test_paths`: paths to the test files written in Step 1
- `review_file`: path for the review report, named `review_{attempt}_{subtask_slug}.md` in the plan subfolder
- `plan_subfolder`: absolute path to the plan subfolder

#### Step 4 — Evaluate and Decide
Read the review report. Pass/fail is determined by the review subagent's verdict — not your own judgment.

**If PASS:**
- Edit `plan.md` and mark the subtask `[x] complete`
- Append a PASS entry to `cycle_log.md` in the plan subfolder
- Update the `## Notes` section of `plan.md` with salient findings from the review
- Proceed to the next subtask

**If FAIL:**
- Append a FAIL entry to `cycle_log.md` with: verdict, artifact file names, issue summary, action taken
- Update `## Notes` in `plan.md` with salient findings
- Decide retry strategy:
  - **Worker fell into a trap** (plan is sound, execution failed): retry with augmented custom instructions
  - **Plan is flawed** (subtask requirements or approach are wrong): edit the subtask in `plan.md`, then retry

**If 3 attempts are exhausted without PASS:**
- Mark the subtask `[!] failed` in `plan.md`
- Stop the cycle
- Present a structured escalation report:
  - Summary of all attempt handoff/review artifacts (filenames + one-line summary)
  - Your diagnosis of the root cause
  - Proposed solutions or paths forward
- Wait for user guidance before continuing

### cycle_log.md Format

Maintain `cycle_log.md` in the plan subfolder. Append one block per attempt:

```markdown
## Subtask N: <name>
### Attempt N — PASS/FAIL
- Worker: handoff_{n}_{slug}.md
- Review: review_{n}_{slug}.md
- Issue: <one-line summary, or "None">
- Action: <what you did next, or "Subtask complete">
```
