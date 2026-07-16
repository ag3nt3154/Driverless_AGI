---
name: update-project-context
description: Create or update AGENTS.md at the project root — a living, continuously-updated technical overview that gives any future session a fast picture of the project without re-reading the whole repo. Sections are deliberately lean: Overview, Rules, Process Flow, Architecture, Key Files & Directories, a capped Errors log, Notes & Terms, and a trimmed User Insights (subsections capped at 10 one-liners each). Use whenever the user says "update project context", "update agents.md", "refresh the context doc", "create project context", or "update the docs". Also invoke automatically at the end of every task, and proactively mid-session after a major architectural change.
---

# Update Project Context

You are creating or updating `AGENTS.md` at the project root. This document is a living overview any future session can skim in under 5 minutes to understand current project state. It is updated at the end of every task, so it must stay lean — bloat compounds fast when a file is rewritten this often.

## Mode Detection

- **Creating**: `AGENTS.md` does not exist. This is a rare, one-off event — gather broadly (see Step 1a).
- **Updating**: `AGENTS.md` exists. This is the common case, happening after every task — gather narrowly (see Step 1b).

## Step 1a: Gather Context (creation only)

Only on first creation, when there is no prior document and no task context to lean on:

- Read `README.md`, `TODO.md`, `.dagi/agents.md` (behavioral guidelines — do not duplicate its content here)
- Run `git log --oneline -20` and `git status`
- List top-level directories (1 level deep)

## Step 1b: Gather Context (updates — the common case)

Do **not** re-read README, TODO, or `.dagi/agents.md` — the session that just finished the task already has that context fresh; re-reading them is wasted work and the main source of bloat.

Instead:
- Read the existing `AGENTS.md` first
- Rely on what happened in this session: files touched, decisions made, errors hit, `git diff`/`git status` of the current change
- Only read additional files if something is genuinely unclear from session context alone

## Step 2: Write AGENTS.md

Use this template. Every section should be skimmable in seconds — prefer bullets and short tables over prose.

---

```
# AGENTS.md

> Last updated: {YYYY-MM-DD}

---

## Overview

{2-4 sentences: what the project is, what it does, who/what uses it, and the
core problem it solves. Merge "what" and "why" — do not split into separate
Description/Objective sections.}

## Rules

{Behavioral rules relevant to this specific project. Same substance as
`.dagi/agents.md` for this project's rules — this section is written for
quick human/session orientation; `.dagi/agents.md` remains the mechanism
actually auto-loaded into the system prompt at runtime. Short, imperative
bullets.}

- {rule}

## Process Flow

{Numbered, step-by-step main execution path. Name key functions/files/services.
Update only if this session changed the flow — otherwise leave untouched.}

## Architecture

{High-level components and how they relate. Short bullet list or ASCII diagram.
Shape of the system, not implementation detail.}

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `path/to/file.py` | One-line description |

{Only non-obvious, load-bearing entries. Aim for well under 20 rows. If this
table is growing every session, it's a sign entries need pruning, not just
adding.}

## Errors Log

{Capped at the 10 most recent entries. Each entry is ONE line: error + fix,
no cause paragraphs. When adding a new entry past the cap, drop the oldest.}

- **{YYYY-MM-DD}**: {error} → {fix}

## Notes & Terms

{Merged gotchas + glossary. Each bullet is either a surprising constraint/
workaround, or a domain term worth defining. Keep this the most heavily
curated section — prune stale or superseded entries rather than only adding.}

- **{Term or gotcha}**: {one or two sentences}

---

## User Insights

> Independent observations — not highlighted by the user. Be specific and
> honest. Each subsection is capped at 10 points, each point a single line.

### User Tendencies
{Observed patterns in how the user works, prioritizes, or communicates. Max
10 one-line bullets.}

### Project Shortcomings
{Weaknesses the project has that the user may not be emphasizing: missing
tests, hardcoded config, security gaps, scalability ceilings. Max 10
one-line bullets.}

### Potential Areas of Exploration
{Directions the project could profitably go that have not been discussed:
optimizations, missing features, integration opportunities. Max 10 one-line
bullets.}
```

---

## Step 3: Updating Rules

- **Overview**: touch only if this session changed it structurally. Otherwise leave as-is.
- **Rules**: add a rule when the user gives a project-specific standing instruction; keep in sync with `.dagi/agents.md` for this project. Remove rules no longer accurate.
- **Architecture / Process Flow**: touch only if this session changed them structurally. Otherwise leave as-is.
- **Key Files & Directories**: add entries this session's work made load-bearing; remove entries no longer accurate or load-bearing. This table should not grow monotonically.
- **Errors Log**: append one line for a new error this session actually hit (never speculate). Compress to `**{date}**: {error} → {fix}`. Enforce the cap of 10 — when adding the 11th, drop the oldest.
- **Notes & Terms**: add anything genuinely surprising discovered this session; prune superseded entries.
- **User Insights**: actively revise — sharpen vague entries, remove inaccurate ones, add new observations. Each subsection capped at 10 one-line points — merge or drop the weakest when adding an 11th. This section should read as accurate today, not as an archive of every observation ever made.

Preserve content that is still accurate. Do not rewrite sections that have not changed.

## Step 4: Confirm and Save

Write `AGENTS.md` to the project root. Then briefly report:
- Whether this was a creation or an update
- Which sections changed and why
- Anything pruned (dropped errors-log entry, removed stale note, etc.)

## Guidelines

**Trigger discipline**: run this at the end of every task. Also run it proactively mid-session if something major happens (a structural/architectural change) — don't wait for task end in that case.

**On length**: this is the top priority for this skill. If a section is growing every update, that's a signal to prune, not a signal it's working. The whole document should stay a 5-minute read regardless of how many sessions have touched it.

**On the Errors Log cap**: the cap exists because this doc updates after every task — an uncapped append-only log is exactly what makes documents like this unreadable over time. Git history is the durable record; this log is only for the most recent, still-relevant issues.

**On dates:** Always ISO format (YYYY-MM-DD). Never write "recently" or relative dates.

**On User Insights**: still the most valuable part of the document — write it as an honest briefing for a future session that has never spoken with this user. 3 subsections, each capped at 10 one-liners — sharpen and consolidate rather than let any subsection hit the cap and stay there.

**On description vs README**: Overview and Architecture complement `README.md`, not duplicate it. Link to README for setup/usage instead of repeating it.

**On behavioral guidelines:** `.dagi/agents.md` (per-project) is the mechanism actually loaded into the system prompt at runtime — it holds rules for operating as a coding agent generally (dagi-root copy) or rules specific to whatever project dagi is pointed at (project-path copy). `AGENTS.md`'s Rules section is the same substance as the project-path `.dagi/agents.md`, written for quick orientation — keep the two in sync rather than avoiding overlap. Do not, however, duplicate `.dagi/agents.md`'s content into other `AGENTS.md` sections (Architecture, Notes & Terms, etc.) — Rules is the one section where overlap is expected.
