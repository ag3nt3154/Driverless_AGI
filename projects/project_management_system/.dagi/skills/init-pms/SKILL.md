---
name: init-pms
description: Initialise the PMS folder structure and create all six blank wiki stub documents
---

# init-pms — Initialise Project Management System

## Purpose

Set up the standard folder structure and blank wiki stubs for a new project management
system workspace. Run this skill exactly once, at the start of a new project.

It is safe to re-run if interrupted: check whether each file already exists before
writing it, and skip any that do.

---

## Step 1 — Verify the working location

Use `find` with pattern `*` and path `.` to list the top-level contents of the project
root. Confirm you are in the correct project directory before proceeding. If `wiki/` or
`raw/` already exist, note which files are present so you can skip creating them later.

---

## Step 2 — Create directory structure

Use `bash` to create the full directory tree in one command:

```bash
mkdir -p raw wiki/sources/emails wiki/sources/docs wiki/sources/meetings wiki/sources/misc
```

If `bash` is unavailable, proceed directly to Step 3 — the `write` tool creates parent
directories automatically, so writing the stub files will create all required directories
as a side effect.

---

## Step 3 — Write the six wiki stub documents

For each file below, attempt `read` on the target path first. If the file already exists
and has real content, skip writing it and note this in your final report. Only write
files that are missing or empty.

### 3a — `wiki/readme.md`

```markdown
# Project Overview

> **Status:** Draft — last updated: YYYY-MM-DD

## Use Case

_To be completed._

## Architecture

_To be completed._

## Key Contacts

| Name | Role | Contact |
|------|------|---------|
| — | — | — |

## Features

| Feature | Description | Status | Added | Source |
|---------|-------------|--------|-------|--------|
| — | — | Planned | — | — |
```

### 3b — `wiki/schedule.md`

```markdown
# Schedule & Milestones

> **Last updated:** YYYY-MM-DD

## Active Tasks

<!-- Format: - [ ] Task description — Due: YYYY-MM-DD | [[sources/{type}/filename]] -->
<!-- Use "Due: TBD" when no deadline is known; add a corresponding entry in open_questions.md -->

_No tasks recorded yet._

## Completed Tasks

<!-- Move completed items here with: - [x] Task description — Completed: YYYY-MM-DD -->

_None yet._

## Milestones

| Milestone | Target Date | Status | Source |
|-----------|-------------|--------|--------|
| — | — | Pending | — |
```

### 3c — `wiki/deliverables.md`

```markdown
# Deliverables

> **Last updated:** YYYY-MM-DD

## Client Deliverables

<!-- Tangible outputs expected by stakeholders. -->

| Deliverable | Recipient | Due Date | Status | Source |
|-------------|-----------|----------|--------|--------|
| — | — | — | Pending | — |

## Analysis & Business Inquiries

<!-- Questions, analysis requests, or investigations raised by stakeholders. -->

| Inquiry | Raised By | Date Raised | Status | Source |
|---------|-----------|-------------|--------|--------|
| — | — | — | Open | — |
```

### 3d — `wiki/decisions.md`

```markdown
# Decisions Log

> **Last updated:** YYYY-MM-DD

| # | Decision | Rationale | Date | Owner | Source |
|---|----------|-----------|------|-------|--------|
| 1 | — | — | — | — | — |
```

### 3e — `wiki/open_questions.md`

```markdown
# Open Questions

> **Last updated:** YYYY-MM-DD

## Pending

| # | Question | Context | Raised | Source |
|---|----------|---------|--------|--------|
| 1 | — | — | — | — |

## Resolved

| # | Question | Resolution | Resolved | Source |
|---|----------|------------|----------|--------|
| — | — | — | — | — |
```

### 3f — `wiki/index.md`

```markdown
# Source Index

> **Last updated:** YYYY-MM-DD

This file maps every ingested source document to the wiki pages it informed.
It is auto-maintained by the `ingest-raw` skill — do not edit manually.

| Source File | Type | Ingested | Wiki Documents Updated | Notes |
|-------------|------|----------|------------------------|-------|
| — | — | — | — | — |
```

---

## Step 4 — Final report

After completing all writes, report to the user:

- List each file written (or skipped if it already existed).
- Confirm the full directory tree that was created.
- Remind the user: place raw source files into `raw/` and then invoke the `ingest-raw`
  skill to populate the wiki.

---

## Edge Cases

- **File already exists with content:** Skip it. Do not overwrite real content.
- **Interrupted mid-run:** The skill is idempotent. Re-invoke it; it will only write the
  missing files.
- **`bash` unavailable or fails:** `write` creates parent directories automatically.
  Proceed by writing stub files directly.
- **Wrong working directory:** If `find` reveals unexpected contents (no `.dagi/` folder,
  wrong project name), stop immediately and inform the user before writing anything.
