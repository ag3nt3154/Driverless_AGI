---
name: deliver
description: Execute an approved plan with per-subtask review and integrated verification; return results to the calling workflow.
triggers: /deliver, deliver this, implement this, build this
---

# deliver

This skill is the execution and verification stage owned by `enter-workflow`.
It runs work, per-subtask review, and integrated verification. The main agent reads
every agent result before deciding the next step.

## Execute with per-subtask review

For each pending or accepted-but-uncommitted subtask (in order):

1. Spawn a worker agent to implement the subtask.
2. Spawn a reviewer agent to review the subtask's diff, acceptance criteria, and test commands.
3. On ESCALATE, repair and re-review. On PASS, stage and commit the accepted changes with a Conventional Commit message. Verify the commit succeeded.
4. On the plan document, mark the subtask as completed and add any notes from the review. The main agent alone edits plan progress (subtask markers, plan notes).

## Constraints

- The main agent alone edits plan progress (subtask markers, plan notes).
  Workers receive assignments; they do not edit the plan, stage files, or commit.
- No fixed attempt count, implementation budget, or time limit on any phase.
  Unresolved blockers return to the main agent for decision.
- User stop is always respected. If the user stops mid-delivery, the plan remains
  tracked for resumption via `deliver`.
- Standalone `write-plan` writes the artifact and returns without delivery.
- Requirement or scope changes return to the owner for the affected planning/approval
  stage. Local implementation repairs remain inside the execution/review loop.
