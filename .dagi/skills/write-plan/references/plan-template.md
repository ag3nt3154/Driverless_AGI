# [Feature Name] Implementation Plan

**Goal:** [One sentence describing what this builds]
**Architecture:** [2-3 sentences about approach]
**Tech Stack:** [Key technologies/libraries]
**Spec:** [path to spec.md in the same artifact directory]

## Global Constraints
Project-wide requirements from the spec — one line each.

## Review Focus
Uncovered failure modes — one line each with owning task's test.

---

## Workspace
- **Branch:** `<task-branch>`
- **Parent:** `<parent-branch>`
- **Starting commit:** `<commit-hash>`
- **Artifact directory:** `wiki/tasks/YYYY-MM-DD_<task>/`

## Overall Status
Pending / In Progress / Verification / Complete / Blocked

## Subtasks

### Subtask 1: [ ] <name>
**Goal:** One sentence.
**Requirements:**
- Bulleted list of what must be true.
**Acceptance Criteria:**
- Bulleted list of checkable conditions.
**Files:**
- Exact paths and the changes each receives.
**Interfaces:**
- Inputs, outputs, and contracts used by this task.
#### Tests
Test file paths and one-line description of what each verifies.
#### Steps
- [ ] Write the failing test or define the passing baseline.
- [ ] Run the focused test and record the expected result.
- [ ] Implement the smallest change that satisfies the task.
- [ ] Run the focused test again and record the result.
- [ ] Return changed files, test evidence, and deviations for review.

## Notes
Record exploration findings and approval evidence here. Before a verified commit,
record review accepted / commit pending; after verification, record the commit ID.

## Open Issues
Unresolved questions or blockers not yet addressed.

## Attempts and Resolutions
One block per rework cycle:
- **Subtask N, attempt N:** blocker summary → resolution (or link to handoff)

## Verification
End-to-end verification commands and expected outcomes.

## Next Action
One sentence: what happens next after reading this plan.
