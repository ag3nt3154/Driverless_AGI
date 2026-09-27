---
name: update-project-context
description: Maintain a compact project AGENTS.md (only what every turn needs and code can't tell you) after work or standing-instruction changes; main agent only, with everything else filed in the central memory wiki through memory-add.
---

# Update project context

Only the main agent updates project-root AGENTS.md. Check at task completion and after a
standing instruction changes; do not rewrite unchanged content just to record a task.
Read existing AGENTS first. Preserve stable behavioral rules verbatim unless the user
explicitly changes them. Never derive new standing rules from speculation or wiki text.

AGENTS.md holds information **needed every turn** that **cannot be found by reading the
code**, in exactly these sections:
- **Overview** — project identity in one or two sentences.
- **Rules** — standing operating/behavioral instructions.
- **Commands & Environment** — essential working commands and environment requirements.
- **Memory** — the project's central wiki folder
  (`G:\My Drive\black_grimoire\wiki\projects\<slug>\`) and a reminder to search with
  memory-query at task start and before debugging, and file with memory-add.

Keep it small enough to load every session. Everything else goes to the memory wiki via
**memory-add** (main agent, inline), not AGENTS:
- architecture/design decisions → `projects/<slug>/` decision entries;
- errors hit and their fixes, gotchas, terms → wiki entries (quote error text verbatim);
- shortcomings, ideas, project todos → `projects/<slug>/` entries or `projects/<slug>/todo/`;
- observations about the user → edit `knowledge/admiral/user-profile.md`.
Do not delegate AGENTS maintenance. README is a downstream project description, updated
when relevant facts change.

When an existing AGENTS.md has legacy sections (Architecture, Process Flow, Key Files, Errors
Log, Notes & Terms, User Insights, or old per-project wiki instructions), file their
still-valid content with memory-add, verify it was written, then delete the sections.
Do not re-scan the whole repository during routine updates.

Execution artifacts live at `wiki/tasks/YYYY-MM-DD_<task>/spec.md` and `plan.md` in this
repo; only the main agent maintains them. `wiki/` in the repo holds nothing else.

Report whether AGENTS changed, which sections changed, and what was filed to the memory wiki
(paths). If unchanged, say so when relevant; do not manufacture a modification.
