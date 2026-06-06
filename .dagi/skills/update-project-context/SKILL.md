---
name: update-project-context
description: Create or update PROJECT_CONTEXT.md at the project root — a living technical design document that gives future sessions a complete picture of the project before they start any work. Sections include project description, objectives, architecture, process flow, encountered errors and solutions, notable gotchas, terms/glossary, and a Claude Insights section with honest observations about the user's tendencies, project shortcomings, unchallenged assumptions, dependency risks, and exploration opportunities. Use whenever the user says "update project context", "update PROJECT_CONTEXT.md", "refresh the context doc", "create project context", or "update the docs". Also invoke proactively at the end of any significant task — especially after fixing bugs (add to errors log), after architectural changes (update architecture section), or when you notice something non-obvious about the project state.
---

# Update Project Context

You are creating or updating `PROJECT_CONTEXT.md` at the project root. This document is the primary orientation artifact for any future session working on this project. It should give a complete, honest picture of the project's current state, the work done so far, and non-obvious observations a fresh developer (or future session) would need before starting work.

## Mode Detection

Determine which mode you are in before starting:

- **Creating**: `PROJECT_CONTEXT.md` does not exist. Gather context broadly and write all sections.
- **Updating**: `PROJECT_CONTEXT.md` exists. Read it first. Update only what has changed. Append to the errors log — never remove entries. Refresh the Insights section with anything new you have observed this session.

## Step 1: Gather Context

Run these reads in parallel. Skip gracefully if a file does not exist.

**Documents to read:**
- `PROJECT_CONTEXT.md` (if updating — read this first, before anything else)
- `README.md`
- `todo.md` or `TODO.md`
- `.dagi/agents.md` (behavioral guidelines — do not duplicate in PROJECT_CONTEXT)
- Any `ARCHITECTURE.md`, `DESIGN.md`, or top-level `docs/` folder

**Shell commands to run:**
- `git log --oneline -20` — recent commit history and direction of work
- `git status` — current working state, uncommitted changes
- List top-level directories (1 level deep) — understand the project layout

**Do not** read every source file. Focus on entry points, configuration files, and any files mentioned prominently in recent commits or the README. The goal is orientation, not exhaustive coverage.

## Step 2: Write PROJECT_CONTEXT.md

Use this template exactly. Adapt depth to the project. Keep the document readable in under 5 minutes; use bullets and tables, not paragraphs.

---

```
# PROJECT_CONTEXT.md

> Last updated: {YYYY-MM-DD} | [README](README.md) | [TODO](todo.md)

---

## Project Description

{1-3 sentences: what it is, what it does, who uses it.}

## Objective / Problem Statement

{What problem does this solve? What is the end goal?
Any explicit constraints or non-goals worth stating?}

## Environment

- **Language:** {e.g. Python 3.11+}
- **Runtime:** {e.g. conda env `dagi`}
- **Install:** {command}
- **Run:** {command}
- **Config:** {config file and key fields}

## Architecture

{High-level components and how they relate.
Use a short bullet list or ASCII diagram.
Include directory layout for non-trivial projects.}

## Process Flow

{Step-by-step main execution path.
Number the steps. Name the key functions, files, or services.}

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `path/to/file.py` | One-line description |

{Only include non-obvious entries. Skip files whose names are self-explanatory.}

## Encountered Errors & Solutions

{Append-only log. Never remove entries — they are institutional memory.}

- **{YYYY-MM-DD} Error**: {brief description}
  **Cause**: {root cause}
  **Fix**: {what was done to resolve it}

## Notable Points

{Things that would surprise a new developer: gotchas, non-obvious constraints,
workarounds, and deliberate design decisions that look strange without context.}

- {point}

## Terms & Language

{Glossary of domain-specific terms, abbreviations, and project-specific language.}

- **{Term}**: {definition}

---

## Claude's Insights

> Independent observations — things NOT mentioned or highlighted by the user.
> Be specific. "Tends to skip error handling" is useful. "Is a good developer" is not.

### User Tendencies
{Observed patterns in how the user works, prioritizes, or communicates.}

### Project Shortcomings
{Weaknesses the project has that the user may not be emphasizing.}

### Assumptions to Challenge
{Things the project implicitly assumes that may not hold under real conditions.}

### Dependencies & Risks
{External dependencies or services that pose meaningful risk if they change or fail.}

### Potential Areas of Exploration
{Directions the project could profitably go that have not been discussed.}
```

---

## Step 3: Updating Rules

When **updating** an existing `PROJECT_CONTEXT.md`:

- **Errors log**: append new entries at the bottom. Never delete old entries.
- **Architecture / Process Flow**: update only if something structurally changed this session.
- **Notable Points**: add anything non-obvious discovered during the current task.
- **Terms**: add any new project-specific language introduced in recent work.
- **Insights**: actively revise — add new observations, sharpen vague ones, remove inaccurate ones.

Preserve existing content where it is still accurate.

## Step 4: Confirm and Save

Write `PROJECT_CONTEXT.md` to the project root. Then briefly report:
- Whether this was a creation or an update
- Which sections changed and why
- The most notable insight added or revised (one sentence)

## Guidelines

**On the Insights section:** Write it as a briefing for a future session that has never spoken with this user. Be specific and honest. A sanitized Insights section is worse than none.

**On dates:** Always use ISO format (YYYY-MM-DD). Never write "recently" or relative dates.

**On length:** Target a 5-minute read. If the errors log exceeds 20 entries, group by component or date range.

**On the errors log:** Only add entries based on things that actually happened — never speculate.

**On behavioral guidelines:** Do NOT copy content from `.dagi/agents.md` into PROJECT_CONTEXT.md. The two files are complementary: agents.md = how to behave; PROJECT_CONTEXT.md = what the project is.
