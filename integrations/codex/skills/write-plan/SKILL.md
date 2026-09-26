---
name: write-plan
description: Write a concrete implementation plan from a spec or settled requirements, with task contracts and verification; return the artifact without starting implementation.
---

# Implementation-plan writer

This is a writing stage. `enter-workflow` owns approval, independent review, commits,
execution, and finishing. Return the artifact and readiness to it. A standalone invocation
writes only the plan; it does not launch the lifecycle or authorize implementation.

Read the spec and existing source needed to ground the plan. Use the owner's already selected
`wiki/tasks/YYYY-MM-DD_<task>/` directory and Git checkpoint. Do not recompute paths on resume.
Standalone: honor a supplied path; otherwise select that task directory once from the stated
task and date. Create missing parent directories, preserve unrelated existing artifacts, and
record any unknown Git field as an explicit blocker for execution rather than inventing it.

## Shared format

Read [plan-template.md](references/plan-template.md) and populate it as `plan.md`. This is the
same template used by delivery, not a second private schema. Fill Workspace before approval:
actual branch, parent, starting commit, and artifact directory. Keep `<task-branch>` host
neutral in the reference; fill the recorded branch, including explicit prefix overrides.

Replace guidance/placeholder text with task-specific content, preserving `[ ]` status/step
markers. Include the spec link and copy its exact global constraints. Identify the most
consequential uncovered failure modes in Review Focus, and assign their checks to the task
owning that behavior. An empty focus section means none remain, with that conclusion stated.

Each `### Subtask N: [ ] Name` contains Goal, Requirements, Acceptance Criteria, Files,
Interfaces, `#### Tests`, and concrete Steps. Use sequential unique task numbers. Record
pending approval/review honestly; writing the plan is not evidence that either occurred.

## Task design

Map changed files and responsibilities before decomposing work. Follow existing patterns;
avoid speculative architecture or unrelated refactoring. A subtask is a deliverable that can
be independently tested and reviewed. Fold setup/docs into the behavior that needs them;
split where a reviewer could reject one deliverable while accepting its neighbor.

Give each implementer enough context to work without guessing:
- Exact file paths and purpose of each change; distinguish new versus existing files.
- Consumed/produced interfaces and types, including cross-task dependencies.
- Checkable behavior, defaults, edge cases, and required failures.
- Concrete implementation steps and code/test examples where needed to remove ambiguity.
- Actual verification commands and expected outcomes, using the required project environment.

Tasks follow `do-tdd`: expected behavioral red, smallest passing implementation, and relevant
regression checks. Pure refactors start with passing coverage. Documentation and other work
without meaningful automated tests must name the limitation and an appropriate alternative
check. Do not invent tests to satisfy process. Do not put staging/commit commands in worker
steps; the main agent reviews and commits accepted subtasks under scoped approval.

Keep branch finishing out of worker tasks. The owner presents the completed verified branch
for merge/keep after delivery; no subtask creates a new user approval gate. Make global
installation or other external writes explicit in the plan's scope and acceptance criteria.

## Self-review and return

Check every spec requirement has an owning task and verification. Resolve missing contracts,
inconsistent names/types, vague "handle errors" steps, and implementation-blocking unknowns.
No unresolved filler such as "TBD", "implement later", or references to undefined interfaces.
Read the complete plan as an executor: Workspace must exist before delivery's entry checks,
and global Verification must cover the whole result, not only isolated unit tests.

Use Notes/Next Action for the checkpoint. Preserve valid approval on narrow revisions; report
material scope changes to the owner. A reviewed-but-uncommitted task stays `[~]` with commit
pending in Notes; `[x]` requires verified commit evidence or an accepted documented no-op.

Return the plan path, requirement coverage, readiness, and unresolved blockers. Do not invoke
`deliver`, commit documents, or treat saving the file as user approval.
