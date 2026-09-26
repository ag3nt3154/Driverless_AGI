---
name: write-plan
description: Use when you have a spec or requirements for a multi-step task, before touching code
---

# Writing Plans

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable taste. Document everything they need to know: which files to touch for each task, code, testing, docs they might need to check, how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

**Announce at start:** "I'm using the `write-plan` skill to create the implementation plan."

**Save plans to:** `wiki/tasks/YYYY-MM-DD_<task>/plan.md`

Use the artifact directory already selected by `enter-workflow`; do not recompute it on
resume. Record the supplied parent/task branch names and starting commit in plan Notes.
The owner presents spec and plan together for approval and commits both before delivery.

Implementation tasks follow `do-TDD` (runtime name `do-tdd`), supplied by `deliver` to
the implementer. Describe the expected failing behavior and relevant checks; for pure
refactoring, specify passing baseline coverage. Flag changes without meaningful automated
tests and propose alternative verification. Keep final branch finishing outside worker
tasks: `enter-workflow` invokes `merging-git-branch` after delivery verification.

## File Structure

Before defining tasks, map out which files will be created or modified and what each one is responsible for. This is where decomposition decisions get locked in.

- Design units with clear boundaries and well-defined interfaces. Each file should have one clear responsibility.
- You reason best about code you can hold in context at once, and your edits are more reliable when files are focused. Prefer smaller, focused files over large ones that do too much.
- Files that change together should live together. Split by responsibility, not by technical layer.
- In existing codebases, follow established patterns. If the codebase uses large files, don't unilaterally restructure - but if a file you're modifying has grown unwieldy, including a split in the plan is reasonable.

This structure informs the task decomposition. Each task should produce self-contained changes that make sense independently.

## Task Right-Sizing

A task is the smallest unit that carries its own test cycle and is worth a
fresh reviewer's gate. When drawing task boundaries: fold setup,
configuration, scaffolding, and documentation steps into the task whose
deliverable needs them; split only where a reviewer could meaningfully
reject one task while approving its neighbor. Each task ends with an
independently testable deliverable.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Return implementation and test evidence for review" - step

The main agent commits after the whole subtask passes review, not after each TDD step.
Do not put Git staging/commit commands in worker instructions.

## Plan Document Format

Load and fill the canonical reference at
`references/plan-template.md` beside this skill file. Copy it into the selected
task artifact directory and replace every bracketed slot with concrete content.
The header must contain Goal, Architecture, Tech Stack, and Spec, followed by
Global Constraints and Review Focus. Populate Workspace before approval.

## Task Structure

Use each `### Subtask N: [ ] Name` block from the canonical reference. Every task
must include concrete Goal, Requirements, Acceptance Criteria, Files, Interfaces,
`#### Tests`, and executable Steps. Include exact paths, interfaces, test behavior,
and expected red/green evidence so workers can act without guessing.

## No Placeholders

Every step must contain the actual content an engineer needs. These are **plan failures** — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the code — the engineer may be reading tasks out of order)
- Steps that describe what to do without showing how (code blocks required for code steps)
- References to types, functions, or methods not defined in any task

## Self-Review

After writing the complete plan, look at the spec with fresh eyes and check the plan against it. This is a checklist you run yourself — not a subagent dispatch.

**1. Spec coverage:** Skim each section/requirement in the spec. Can you point to a task that implements it? List any gaps.

**2. Placeholder scan:** Search your plan for red flags — any of the patterns from the "No Placeholders" section above. Fix them.

**3. Type consistency:** Do the types, method signatures, and property names you used in later tasks match what you defined in earlier tasks? A function called `clearLayers()` in Task 3 but `clearFullLayers()` in Task 7 is a bug.

**4. Review Focus:** For each input class or failure mode the spec implies, is there a task whose tests exercise it? The five uncovered ones most likely to bite a person go in the Review Focus section, and each line there gets its test added to the owning task. An empty section means you checked and found none, not that you skipped the check.

If you find issues, fix them inline. No need to re-review — just fix and move on. If you find a spec requirement with no task, add the task.

## Return to caller

After saving and self-reviewing, return the plan path, requirement coverage, and any
unresolved blockers to `enter-workflow`. It owns user approval, independent review,
commits, active-plan attachment, and transition to delivery.

Do not launch another lifecycle or invoke `deliver`. When invoked standalone, report
the written plan and readiness only; writing a plan does not authorize implementation.
