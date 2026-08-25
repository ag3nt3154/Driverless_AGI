---
name: update-project-context
description: Use when creating, compressing, or updating a project's AGENTS.md, including end-of-task context refreshes and standing-instruction changes.
---

# Update Project Context

Create or update the project-root `AGENTS.md`: a compact operational briefing injected into
future sessions. It is not architecture documentation, a roadmap, or a project diary. Preserve
instructions and hard-won operational knowledge; link to durable docs for everything else.

**Output target:** 1,500–2,000 tokens when the stable behavioral rules require that much; shorter
is welcome. Treat the budget as a forcing function, not permission to delete required instructions.

## Mode Detection

- **Creating**: `AGENTS.md` does not exist. This is a rare, one-off event — gather broadly (see Step 1a).
- **Updating**: `AGENTS.md` exists. This is the common case, happening after every task — gather narrowly (see Step 1b).

## Step 1a: Gather Context (creation only)

Only on first creation, when there is no prior document and no task context to lean on:

- Read `README.md`, `TODO.md`
- Run `git log --oneline -20` and `git status`
- List top-level directories (1 level deep)
- If `/init` supplied an empty `## Behavioral Guidelines`, fill it with actual project standards.

## Step 1b: Gather Context (updates — the common case)

Do **not** re-read README or TODO — the session that just finished the task already has that context fresh; re-reading them is wasted work and the main source of bloat.

Instead:
- Read the existing `AGENTS.md` first
- Rely on what happened in this session: files touched, decisions made, errors hit, `git diff`/`git status` of the current change
- Only read additional files if something is genuinely unclear from session context alone

## Step 2: Write AGENTS.md

Use exactly this section model. Omit `Process Flow`, `Errors Log`, or `Notes & Terms` when there is
nothing useful to say. Do not add architecture, key-file catalogs, user profiles, shortcomings, or
idea backlogs; those belong in README, TODO, issue tracking, or dedicated design documents.

---

```
# AGENTS.md

> Last updated: {YYYY-MM-DD}

---

## Overview

{1-2 sentences: what the project is and does. Link README for setup and detail.}

## Rules

{Project-specific standing instructions. Short, imperative bullets.}

- {rule}

## Behavioral Guidelines

{Stable protocol/standards content — coding standards, session protocol,
ambiguity calibration, hard stops, etc. This section is force-injected into
every session's system prompt alongside the rest of this document (same
mechanism `.dagi/agents.md` used to serve). PRESERVE VERBATIM across routine
updates — do not regenerate or rephrase it from session diffs. Only edit it
when the user gives an explicit standing behavioral instruction.}

## Process Flow

{Optional: 3-6 numbered lines describing the main runtime or delivery path.
Name only the boundary files/services needed to orient a new session.}

## Errors Log

{Optional: at most 5 unresolved or recurrence-prone failures. One line each. A
normal completed bugfix does not automatically deserve an entry.}

- **{YYYY-MM-DD}**: {error} → {fix}

## Notes & Terms

{Optional: at most 8 non-obvious invariants or required workarounds. One line
each. Keep information that changes how a competent contributor acts.}

- **{Term or gotcha}**: {one sentence}
```

---

## Step 3: Updating Rules

- **Overview**: touch only if this session changed it structurally. Otherwise leave as-is.
- **Rules**: add a rule when the user gives a project-specific standing instruction. Remove rules no longer accurate.
- **Behavioral Guidelines**: leave untouched on routine updates. Only edit when the user explicitly changes a standing behavioral rule.
- **Process Flow**: change only when the main path changes; keep it at 3-6 steps.
- **Errors Log**: record only unresolved or likely-to-recur failures whose workaround remains useful. Remove resolved history and enforce the 5-line cap.
- **Notes & Terms**: add only knowledge that changes future action. Remove facts discoverable quickly from code or README and enforce the 8-line cap.
- **Removed categories**: migrate no content from Architecture, Key Files, User Tendencies, Project Shortcomings, or Potential Areas of Exploration unless a specific item qualifies as an operational rule, live error, or non-obvious invariant.

Preserve required instructions and still-useful operational knowledge. Accuracy alone is not an
inclusion test: current but low-value detail should be pruned.

## Step 4: Confirm and Save

Write `AGENTS.md` to the project root. Then briefly report:
- Whether this was a creation or an update
- Which sections changed and why
- Anything pruned or deliberately not recorded

## Guidelines

**Trigger discipline**: run at the end of every task and after a standing instruction changes.

**On length**: measure before and after. Aim for 1,500–2,000 tokens; never let routine updates
increase the document unless they add a required instruction or replace weaker context. If over
budget, prune descriptive material before rules, then resolved errors, then obvious notes.

**On errors**: Git history is the archive. Keep only failures likely to save a future session from
repeating wasted work; recency alone is insufficient.

**On dates:** Always ISO format (YYYY-MM-DD). Never write "recently" or relative dates.

**On description vs README/TODO**: Overview orients; README explains; TODO tracks future work.
Reference those files instead of copying their contents.

**On behavioral guidelines:** `AGENTS.md` is loaded into the system prompt. `Rules` and
`Behavioral Guidelines` are the only homes for standing instructions; do not duplicate them.

## Inclusion Test

Keep a line only if at least one is true:

1. It is a standing instruction future agents must follow.
2. Omitting it creates a meaningful risk of a repeated error or wasted investigation.
3. It explains a non-obvious runtime boundary needed to choose where to work.

If none applies, delete it or link to its durable home.
