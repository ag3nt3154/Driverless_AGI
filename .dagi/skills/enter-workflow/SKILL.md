---
name: enter-workflow
description: Own the task lifecycle — classify requests, manage stage transitions, approvals, and closure.
triggers: /workflow, /enter-workflow, start workflow, new task
---

# Ownership and entry

Only the main agent runs this lifecycle. `enter-workflow` describes the lifecycle of a task. It owns stage transitions, user approvals, active-plan tracking, and final closure. 

Various skills called during the lifecycle — `grill-me`, `write-spec`,
`write-plan`, `deliver`, and `merging-git-branch` — return their result here as stages;
they do not launch one another.

Loading a skill is not spawning an agent or ending a turn. Continue the owning
workflow after reading its result; ask the user when user input is required.

# Life Cycle

1. Classify the request as a **query**, **bounded**, or **architectural** task. Present the classification to the user for confirmation.
   - **Query** A question from the user. E.g. "Is this true?", "What is process flow for this?", "Can we do X?".
   - **Bounded** A task with clear boundaries and deliverables. E.g. "Fix a bug in this existing module", "Update documentation for this existing API".
   - **Architectural** A task that involves high-level design or structural decisions. E.g. "Design a new module", "Refactor the system architecture".
2. Clarify user intent. Explore the project files, docs and wiki to understand the current state and ask clarifying questions until you understand the request, its scope, and constraints. Invoke `grill-me` to clarify user intent and resolve intent, scope, constraints, and meaningful alternatives until shared understanding is reached.
3. After user confirms your classification, follow the corresponding steps for that task type.
4. After finishing the task, update the project docs in `wiki`. Invoke the `wiki-add` skill to record any new information in the project wiki. Information you should add to the wiki includes: 
   - architectural decisions
   - gotchas
   - errors and fixes
   - terms
   - project shortcomings
   - areas to explore
Update `AGENTS.md` with only information needed every turn that cannot be found by reading the code.

## Query
- The user is requesting an answer to a question. No code changes are necessary. Clarify the question, investigate, and report findings.
- The user may ask to start a **bounded** or **architectural** task based on the answer to the query. If so, follow the corresponding steps for that task type.

## Bounded
- The user is requesting a well-scoped change to existing code. This task is simple and does not require a dedicated spec or plan document.
- Check git for uncommitted or unstaged work before starting. Ask the user how to handle these.
- Produce an inline plan in chat and ask for approval before implementing.
- Implement the change with TDD. Write failing tests, implement the change, and refactor until tests pass.
- Spawn a reviewer subagent with the diff, acceptance criteria from the inline plan, and test commands.
- On ESCALATE, repair and re-review. On PASS, stage and commit the accepted changes with a Conventional Commit message. Verify the commit succeeded.

## Architectural
- The user is requesting a new project, subsystem, or a change that restructures how components fit together or alters interfaces others depend on. This task requires a dedicated spec and plan document.
- Check git for uncommitted or unstaged work before starting. Ask the user how to handle these.
- Present the understood scope, parent branch, proposed `task/<task>` branch, and artifact directory `docs/tasks/YYYY-MM-DD_<task>/`. The `<task>` slug is the same in both. Ask to create and check out that branch. This approval permits branch setup and drafting, not implementation or merging.
- Create a plan by invoking the `write-plan` skill and save it to the artifact directory. 
   Conventions:
   - `docs/tasks/YYYY-MM-DD_<task>/plan.md` (default for `enter-workflow`)
   - A project-specific path from AGENTS.md or the caller's instructions
- Present the plan to the user for approval. Ask explicity to approve the plan. If approved, stage and commit the plan to the task branch with the message `plan: approve plan`. Verify the commit succeeded.
- Invoke the `deliver` skill to implement the plan.
- After all subtasks are reviewed/committed and integrated verification succeeds, ask the user if he wants to merge the task branch into the parent branch.

# Continuation
If the user is asking for a continuation of a previous task, inspect the project status, git history, and `docs` to find out what task and which stage is pending. Resume the lifecycle at the incomplete stage. Ask for approval from the user before continuing.