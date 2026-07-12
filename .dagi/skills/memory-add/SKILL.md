---
name: memory-add
description: Integrate a piece of text into the dagi-memory wiki — determines topic, creates a structured wiki node, updates index files, and appends to log.md. Use when the user wants to save to memory, add to wiki, remember this, store in memory, add to memory, write to wiki, note this down, add this thought, log this, capture this, note this. Prefix the task with "Project: <name>" to route to the projects section.
---

# memory-add

## Purpose

File new knowledge into the dagi-memory wiki with correct structure, metadata, and index
updates. Run this skill whenever the user asks to save, remember, or log something.

---

## Step 0 — Resolve memory root

1. Attempt to read `{cwd}/config.yaml`.
2. If it exists and contains a non-empty, uncommented `memory_root:` key, use that value.
   Strip surrounding quotes and trailing slashes.
3. Otherwise fall back to `{cwd}/dagi-memory`.
4. If the resolved path differs from the default, note it briefly: "Using memory root: {path}".

All subsequent paths are relative to `{memory_root}`.

---

## Step 0.4 — Clarify ambiguities before writing

Before doing anything else (TODO flow or content flow), scan the input for **material
ambiguities** — details that change *what gets written* or *where it goes*, and that you
cannot resolve with high confidence from the input, the wiki, or sensible defaults.

If one or more material ambiguities exist, **ask the user with the `ask_user` tool
before writing anything.** Wait for the answers, then proceed using them. Do not guess on a
material detail and silently write a version you may have to rewrite.

**Material ambiguities worth asking about** (non-exhaustive):
- **Integration / scope target** — *where* something should live or plug in (e.g. which project,
  subsystem, or pipeline a task targets). Inferring the wrong target is a common, costly error.
- **Topic / project routing** — when it is genuinely unclear whether the content is knowledge
  vs. a specific project, or which topic/project it belongs to.
- **Conflicting or contradictory details** in the input.
- **A due date or timeframe** that is implied ("soon", "before the release") but not pinned, when
  the user seems to care about scheduling.
- **The actual subject** — when the input is too terse to tell what concept is meant.

**Do NOT ask about** things you can reasonably infer or default:
- Slug, tags, type, `date_added` — derive these yourself.
- Minor wording of titles or descriptions.
- Anything the input already states plainly.

Keep questions few and high-leverage (prefer 1–2). If nothing is materially unclear, skip this
step entirely and proceed — do not interrogate the user over trivia.

---

## Wiki Structure

```
{memory_root}/
└── wiki/
    ├── .index.md              ← root nav (three rows: Projects, Knowledge, User TODO)
    ├── log.md                 ← append-only operation log
    ├── open_questions.md      ← pending & resolved questions
    ├── user-todo.md           ← personal task & intention tracker (Admiral)
    ├── projects/
    │   ├── .index.md          ← table of all tracked projects
    │   └── {project-name}/
    │       ├── .index.md      ← project page index
    │       ├── context.md     ← project overview, goals, architecture
    │       ├── updates.md     ← append-only decision log
    │       └── {slug}.md      ← other project pages
    └── knowledge/
        ├── .index.md          ← table of all knowledge topics
        └── {topic}/
            ├── .index.md      ← topic page index
            └── {slug}.md      ← knowledge nodes
```

---

## Frontmatter Schema

Every wiki page uses exactly these five fields:

```yaml
---
type: note | entity | source-summary | reflection | insight | analysis | context | update
topic: {topic-name}           # knowledge pages — e.g. machine-learning
                              # project pages   — e.g. project/black-grimoire
description: one-line summary of what this page contains
date_added: YYYY-MM-DD
tags: keyword1, keyword2, keyword3    # comma-separated, grep-friendly
---
```

---

## Step 0.5 — Detect TODO intent

Before classifying, check whether the input expresses a **personal plan or intention** by the
user (the Admiral) to do something in the future.

**Trigger phrases** (case-insensitive, at start or anywhere in input):

```
I want to       I plan to       I need to       I'm going to    I am going to
I will          I should        I intend to     I'd like to     I was thinking of
I'm planning    remind me to    my goal is to   TODO:
```

The input must describe the *user* doing something — not a request for Claude to act right now.

**Examples that trigger this step:**
- "I want to study gamma exposure next week"
- "I plan to refactor the ingestion pipeline before the release"
- "remind me to review open questions on Friday"

**Examples that do NOT trigger:**
- "Remember: gamma exposure increases near expiry" ← factual content for wiki
- "Can you summarise this?" ← direct request to Claude

---

### If TODO intent detected → TODO append flow (skip Steps 1–5)

**a. Read `wiki/user-todo.md`.**

**b. Count existing `[TODO-NNN]` section headers to determine the next number.**
   - Pattern: lines matching `## \[TODO-\d+\]`
   - If none found, start at 001. Pad to 3 digits.

**c. Infer the following fields from the input.** If a field marked *(clarify if unclear)* is
materially ambiguous, resolve it via Step 0.4 (`AskUserQuestion`) before appending — especially
the integration/scope target, which is easy to get wrong.

| Field | How to derive |
|-------|--------------|
| **Task title** | Short imperative phrase (≤ 8 words) summarising the intent |
| **Task description** | Expanded sentence or two — what needs doing and why *(clarify the scope/target if unclear)* |
| **Date due** | Extract explicit date or timeframe ("next week", "by Friday"); convert to YYYY-MM-DD if possible; else `—` *(clarify if implied but unpinned and scheduling matters)* |
| **Proposed method** | Any "by doing X" / "using Y" hints in input; otherwise infer a sensible first step |
| **Related nodes** | Grep `wiki/` for key terms from the content; include up to 3 `[[wikilink]]` paths; else `—` |

**d. Append the following block to `wiki/user-todo.md`:**

```markdown

## [TODO-{NNN}] {Task Title}
- **Date Added**: {YYYY-MM-DD}
- **Date Due**: {YYYY-MM-DD or —}
- **Status**: `pending`
- **Task Description**: {description}
- **Proposed Method**: {method}
- **Related Nodes**: {wikilinks or —}
```

*(Status values: `pending` | `in-progress` | `completed` | `dropped`)*

**e. Append to `wiki/log.md`:**

```
[{YYYY-MM-DD}] add-todo | {task title} | wiki/user-todo.md#TODO-{NNN}
```

**f. Report to the user:**

```
Filed: TODO-{NNN} — {task title}
Path:  wiki/user-todo.md
Action: appended

Modified:
- wiki/user-todo.md — appended TODO-{NNN}
- wiki/log.md — appended entry
```

**Then stop.** Do not proceed to Step 1.

---

**If NOT detected → continue to Step 1 as normal.**

---

## Step 1 — Classify the content

Read the task. Determine:

**Is it project-specific?**
- Does the input start with `"Project: <name>"`?
  - **Yes** → route to `wiki/projects/{project-name}/`. Set `topic: project/{project-name}`.
  - **No** → route to `wiki/knowledge/{topic}/`. Set `topic: {topic-name}`.

Also determine:
- What `type` best describes the content?
- What `topic` (or project name) applies? Use kebab-case.
- What `tags` (3–6 comma-separated keywords) would help grep find it?

---

## Step 2 — Check for existing content

grep the relevant section for key terms from the content:

```
grep(pattern="<key term>", path="{memory_root}/wiki/knowledge/<topic>/")
# or: grep(pattern="<key term>", path="{memory_root}/wiki/projects/<name>/")
```

If no hits in the section, widen to the full wiki:

```
grep(pattern="<key term>", path="{memory_root}/wiki/")
```

Read the section's `.index.md` to see what pages already exist.

- **Strong match found** → update the existing page (add a section or revise text).
- **No match** → create a new page.

---

## Step 3 — Determine slug and path

- Slug: `kebab-case-from-topic`, max 40 chars, no special chars.
- Paths:
  - Knowledge page: `wiki/knowledge/{topic}/{slug}.md`
  - Project page:   `wiki/projects/{project-name}/{slug}.md`

---

## Step 4 — Write the wiki page

Use this template:

```markdown
---
type: {type}
topic: {topic}            # project/{project-name} OR {topic-name}
description: {one-line summary}
date_added: {YYYY-MM-DD}
tags: {tag1}, {tag2}, {tag3}
---

# {Title}

{Content — well-structured markdown. Use ## headings for sections.
 Use [[knowledge/topic/slug]] or [[projects/name/slug]] wikilinks for related pages.}
```

**For project pages of type `context`**, organise body as:
```
## Overview
## Goals
## Architecture / Structure
## Key Decisions
## Known Issues
```

**For project pages of type `update`**, organise body as:
```
## Summary of Changes
## Rationale
## Impact
```

---

## Step 5 — Update index files

After writing the page, update the relevant `.index.md` files. All index files use markdown
tables with a header row. Append new rows — never delete existing rows.

### 5a — Topic or project `.index.md`

Add a row to `wiki/knowledge/{topic}/.index.md` or `wiki/projects/{project-name}/.index.md`:

```markdown
| [Title](slug.md) | {one-line description} | {YYYY-MM-DD} |
```

If the `.index.md` does not exist yet, create it:

```markdown
# {Topic Name or Project Name}

> **Last updated:** {YYYY-MM-DD}

| Page | Description | Date Added |
|------|-------------|------------|
| [Title](slug.md) | {one-line description} | {YYYY-MM-DD} |
```

### 5b — Section `.index.md` (only when adding a NEW topic or project folder)

If this is the first page in a new topic or project, add a row to the section index:

**`wiki/knowledge/.index.md`** — 4 columns:
```markdown
| [topic-name](topic-name/.index.md) | {one-line topic description} | {page count} | {YYYY-MM-DD} |
```

**`wiki/projects/.index.md`** — 3 columns:
```markdown
| [project-name](project-name/.index.md) | {one-line project description} | {YYYY-MM-DD} |
```

Do **not** touch `wiki/.index.md` — it only lists the two static sections (Projects, Knowledge).

---

## Step 6 — Append to log.md

Read `wiki/log.md`, then append one line:

```
[{YYYY-MM-DD}] add | {title} | wiki/{section}/{topic-or-project}/{slug}.md
```

Where `{section}` is `knowledge` or `projects`.

---

## Step 7 — Report to the user

Summarise inline:

```
Filed: {title}
Path:  wiki/{section}/{topic}/{slug}.md
Action: created | updated

Modified:
- wiki/{section}/{topic}/{slug}.md — {what changed}
- wiki/{section}/{topic}/.index.md — added row
- wiki/{section}/.index.md — added topic row (if new topic)
- wiki/log.md — appended entry
```

---

## Guidelines

- One page per distinct concept or project area. Don't cram unrelated things together.
- Keep frontmatter exact: 5 fields, no extras.
- Tags should be specific enough for grep to find the page — prefer technical terms over
  generic words like "overview" or "notes".
- If the project or topic folder doesn't exist yet, create it and its `.index.md` first.
- Never write outside the wiki directory.
- If the wiki is not initialised (`wiki/.index.md` missing), stop and tell the user.
