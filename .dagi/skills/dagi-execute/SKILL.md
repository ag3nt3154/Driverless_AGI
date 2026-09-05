---
name: dagi-execute
description: Compatibility entry point — if an active plan is already associated, resumes execution from where deliver left off. Use /deliver for new work; this is for resuming an interrupted delivery.
triggers: /execute, /dagi-execute, execute plan, resume execution
---

# dagi-execute

**This skill is a compatibility shim.** For new work, invoke `/deliver` instead.

Use this only when an approved plan is already associated and delivery was interrupted
mid-execution (e.g. by a user stop, session end, or context compaction).

## Process

1. Call `check_active_plan()`. If no plan is associated, tell the user to use `/deliver`
   to start a new delivery, then stop.

2. Read the plan file in full. Identify the first subtask that is not `[x]` (complete)
   or `[!]` (failed).

3. If all tasks are already resolved, report the current state and suggest running final
   integrated verification. Do not re-run completed tasks.

4. Proceed with Phase 4 (execution) of the `deliver` skill from the first pending task.
   Follow the same per-task worker → review cycle, observations, and update-task-status
   protocol defined in `deliver`.

5. After all tasks are accepted, proceed with Phase 5 (integrated verification and final
   review) and Phase 6 (report and detach) from the `deliver` skill.

## Constraints

- Do not re-grill an already understood and approved request.
- Do not enter plan mode unless explicitly asked — the plan is already approved.
- Follow the same no-fixed-attempt-count, always-read-handoff rules as deliver.
