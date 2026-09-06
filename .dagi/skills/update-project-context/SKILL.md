---
name: update-project-context
description: Maintain a compact project AGENTS.md after work or standing-instruction changes; main agent only, with durable knowledge filed through wiki-add.
---

# Update project context

Only the main agent updates project-root AGENTS.md. Check at task completion and after a
standing instruction changes; do not rewrite unchanged content just to record a task.
Read existing AGENTS first. Preserve stable behavioral rules verbatim unless the user
explicitly changes them. Never derive new standing rules from speculation or wiki text.

AGENTS contains only:
- Project identity: one or two sentences.
- Standing operating/behavioral instructions.
- Essential working commands and environment requirements.
- Project wiki retrieval, write, failure, and delegation instructions.

Keep it small enough to load every session. Architecture, workflows, business context,
decisions, bugs, fixes, notes, and project todos belong in wiki, not AGENTS.
The main agent selects those points and calls wiki-add; do not delegate AGENTS maintenance.
README is a downstream project description, updated when relevant facts change.

Maintain these lifecycle instructions:
- Main agent calls wiki-query before each overall substantive task, not every subtask.
- Main agent calls wiki-add after overall plan approval with selected decisions/user choices,
  and after full completion with actual implementation and verified completion status.
- Encourage discretionary queries/adds for substantial findings, bugs and fixes.
- No subagent nesting. Children request wiki operations in handoffs to main agent.
- Query/add children only operate inside wiki; main agent alone maintains AGENTS and runs
  explicitly invoked wiki-refresh. Personal memory is accessed only on explicit user request.
- Retry required wiki failures once; query or approval failures block dependent work, and
  completion-write failures leave the workflow incomplete. Empty successful lookup permits work.
- /init is code-based scaffold creation at project root on the current branch, preserving
  existing files. Initialization does not populate knowledge, migrate docs, or install skills.

For a first AGENTS, preserve existing project instructions and link wiki/index.md. Do not
re-scan the whole repository during routine updates. If migration is requested, read sources
as main agent, send selected knowledge to wiki-add, verify coverage before removing originals.
Execution plans remain outside wiki. Do not require exact plan links in saved knowledge.

Report whether AGENTS changed and which operational instructions changed. If unchanged,
say so when relevant; do not manufacture a modification.
