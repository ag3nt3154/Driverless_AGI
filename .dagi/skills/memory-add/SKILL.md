---
name: memory-add
description: >-
  File a new entry into the memory wiki. Subagent protocol — the parent agent
  classifies the content and passes category + metadata; this skill handles
  wiki-internal routing, schema enforcement, index updates, and logging.
  Canonical source for both DAGI subagents and Claude Code skills.
---

# memory-add

## Purpose

File new content into the memory wiki with correct structure, frontmatter, and
index updates. This is a **subagent protocol** — the parent agent resolves
category and conversation-context metadata before invoking. The subagent owns
wiki-internal knowledge (which projects/topics exist, where to file, what to
link).

---

## Memory Root

```
{memory_root} = G:\My Drive\black_grimoire\dagi-memory
```

All paths below are relative to `{memory_root}`. Hardcoded — never resolve from
config or cwd.

---

## Interface (parent → subagent)

| Parameter | Required | Description |
|-----------|----------|-------------|
| `task` | yes | The content to file |
| `category` | yes | `projects` \| `todos` \| `knowledge` \| `events` |
| `deadline` | no | For todos — due date (YYYY-MM-DD) |
| `frequency` | no | For todos — `one-off` \| `daily` \| `weekly` \| `monthly` (default: `one-off`) |
| `date` | no | For events — when it occurred (default: today) |
| `custom_instructions` | no | Freeform guidance from parent |

The subagent derives from wiki context (never passed by parent):
- `project_name` — reads `wiki/projects/.index.md`, matches or creates new
- `topic` — reads `wiki/knowledge/.index.md`, matches or creates new
- `title`, `description`, `tags`, `slug` — derived from content
- `links` — discovered by grepping wiki for related nodes

---

## Wiki Structure

```
wiki/
├── .index.md
├── log.md
├── projects/
│   ├── .index.md
│   └── {project-name}/
│       ├── overview.md
│       └── subtask_{NNN}_{title}.md
├── todos/
│   ├── .index.md
│   └── todo_{NNN}_{title}.md
├── knowledge/
│   ├── .index.md
│   └── {topic}/
│       ├── .index.md
│       └── {title}.md
└── events/
    ├── .index.md
    └── event_{YYYY-MM-DD}_{title}.md
```

---

## Frontmatter Schemas

### Shared fields (all categories)

```yaml
title: Short descriptive name
description: One-line summary
tags: keyword1, keyword2, keyword3
date_created: YYYY-MM-DD
links:
  - "[[category/path/to/related-node]]"
```

### Project overview (overview.md) — additional fields

```yaml
status: active | completed | archived | paused
objective: What "done" looks like
```

### Todo — additional fields

```yaml
status: pending | in-progress | completed | dropped
deadline: YYYY-MM-DD | null
frequency: one-off | daily | weekly | monthly
```

### Event — additional fields

```yaml
date: YYYY-MM-DD    # when the event occurred (distinct from date_created)
```

### Knowledge — no additional fields

---

## Naming Conventions

| Category | Pattern | Example |
|----------|---------|---------|
| Project overview | `wiki/projects/{name}/overview.md` | `projects/dagi/overview.md` |
| Project subtask | `wiki/projects/{name}/subtask_{NNN}_{slug}.md` | `projects/dagi/subtask_003_unify-memory.md` |
| Todo | `wiki/todos/todo_{NNN}_{slug}.md` | `todos/todo_042_buy-tickets.md` |
| Knowledge | `wiki/knowledge/{topic}/{slug}.md` | `knowledge/trading-strategies/momentum.md` |
| Event | `wiki/events/event_{YYYY-MM-DD}_{slug}.md` | `events/event_2026-08-08_memory-unification.md` |

Slugs: kebab-case, max 40 chars, no special characters.
NNN: zero-padded 3-digit sequence number, determined by counting existing files.

---

## Protocol Steps

### Step 1 — Orient within the wiki

Read the relevant section `.index.md` based on `category`:

- `projects` → read `wiki/projects/.index.md`
- `todos` → read `wiki/todos/.index.md`
- `knowledge` → read `wiki/knowledge/.index.md`
- `events` → read `wiki/events/.index.md`

For `projects`: also read the matching project's `.index.md` or `overview.md`
if the content clearly relates to an existing project. If no project matches,
create a new project folder with an `overview.md`.

For `knowledge`: identify the best-fit topic from the index. If no topic
matches, create a new topic folder with `.index.md`.

### Step 2 — Check for existing content

Grep the relevant section for key terms from the content:

```
grep("<key term>", path="wiki/{category}/...")
```

- **Strong match found** → update the existing page (add a section or revise).
- **No match** → create a new page.

### Step 3 — Determine sequence number and path

For numbered categories (todos, project subtasks):
- Count existing files matching the pattern (e.g. `todo_*.md`) to determine
  the next sequence number.
- Zero-pad to 3 digits.

For knowledge and events:
- Derive slug from content. Knowledge uses `{slug}.md`, events use
  `event_{YYYY-MM-DD}_{slug}.md`.

### Step 4 — Write the page

Write the file with:
- Correct frontmatter per category schema (shared + category-specific fields)
- Well-structured markdown body
- `[[wikilinks]]` to related pages discovered in Step 2

**Body conventions:**
- Project `overview.md`: minimum `## Objective`, `## Status`, `## Subtasks`
- Subtasks: freeform (rich content — plans, specs, how-to)
- Todos: minimal or no body (frontmatter is the todo)
- Events: freeform narrative
- Knowledge: freeform, structure from content domain

### Step 5 — Update index files

**5a — Folder `.index.md`:** add a row to the table in the containing folder's
`.index.md`.

If the `.index.md` does not exist yet (new folder), create it:

```markdown
---
title: {Folder Name}
description: {one-line description}
tags: index, {category}
date_created: {YYYY-MM-DD}
links: []
---

# {Folder Name}

> **Last updated:** {YYYY-MM-DD}

| Page | Description | Date Created |
|------|-------------|--------------|
| [{title}]({filename}) | {description} | {YYYY-MM-DD} |
```

**5b — Section `.index.md`:** if this is a new project or topic folder, add a
row to `wiki/projects/.index.md` or `wiki/knowledge/.index.md`.

Do NOT touch `wiki/.index.md` — it only lists the four static sections.

### Step 6 — Append to log.md

Append one line to `wiki/log.md`:

```
[{YYYY-MM-DD}] add | {title} | wiki/{category}/{path}/{filename}
```

---

## Handoff (subagent → parent)

```
Filed: {title}
Path:  wiki/{category}/{...}/{filename}.md
Action: created | updated

Modified:
- {file1} — {what changed}
- {file2} — {what changed}
- wiki/log.md — appended entry
```

---

## Error Handling

- If the subagent cannot match a project or topic, it creates a new one.
- Routing problems (wrong project, duplicates, misclassification) are caught
  later by `memory-refresh` lint scripts.
- If the wiki is not initialised (`wiki/.index.md` missing), state this in
  the handoff and stop.
- Never write outside `{memory_root}/wiki/`.

---

## Guidelines

- One page per distinct concept or project area
- Tags should be specific enough for grep — prefer technical terms over
  generic words like "overview" or "notes"
- If the project or topic folder doesn't exist yet, create it and its
  `.index.md` before writing pages
