---
name: write-plan
description: Write an implementation plan from a spec or requirements for a multi-step task. Return the artifact to the calling workflow for approval.
triggers: /write-plan, write plan, create plan, implementation plan
---

# write-plan

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for the
codebase and questionable taste. Document everything they need to know: which files to
touch for each subtask, code, testing, docs they might need to check, how to test it.
Give them the whole plan as bite-sized subtasks. DRY. YAGNI. TDD. Frequent commits.

## Bite-Sized Step Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" — step
- "Run it to make sure it fails" — step
- "Implement the minimal code to make the test pass" — step
- "Run the tests and make sure they pass" — step
- "Return implementation and test evidence for review" — step

The main agent commits after the whole subtask passes review, not after each TDD step.
Do not put Git staging/commit commands in worker instructions.

## Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Feature Name] Implementation Plan

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

## Global Constraints

[The spec's project-wide requirements — version floors, dependency limits,
naming and copy rules, platform requirements — one line each, with exact
values copied verbatim from the spec. Every subtask's requirements implicitly
include this section.]

---
```

## Subtask Structure

````markdown
### Subtask N: [Component Name]

**Goal:** One sentence.
**Requirements:**
- Bulleted list of what must be true.
**Acceptance Criteria:**
- Bulleted list of checkable conditions.

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

#### Tests
Test file paths and one-line description of what each verifies.

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Return for review**

Report changed files, test commands/results, and deviations. The main agent reviews
and commits this subtask before starting the next one.
````

## Plan template (runtime sections)

The header and subtask structure above are produced during planning. The following runtime
sections are filled during delivery. Retain headings used by the delivery workflow.

```markdown
## Workspace
- **Branch:** `task/<task>`
- **Parent:** `<parent-branch>`
- **Starting commit:** `<commit-hash>`
- **Task folder:** `docs/tasks/YYYY-MM-DD_<task>/`

## Overall Status
Pending / In Progress / Verification / Complete / Blocked

## Notes
Findings from exploration, traps to avoid, architectural constraints.

## Open Issues
Unresolved questions or blockers not yet addressed.

## Attempts and Resolutions
One block per rework cycle:
- **Subtask N, attempt N:** blocker summary -> resolution

## Verification
End-to-end verification commands and expected outcomes.

## Next Action
One sentence: what happens next after reading this plan.
```

## Return to caller

After saving and self-reviewing, return the plan path, requirement coverage, and any
unresolved blockers to the calling workflow. It owns user approval, independent review,
commits, active-plan tracking, and transition to delivery.

Do not launch another lifecycle or invoke `deliver`. When invoked standalone, report
the written plan and readiness only; writing a plan does not authorize implementation.
