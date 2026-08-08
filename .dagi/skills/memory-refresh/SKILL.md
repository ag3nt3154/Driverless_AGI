---
name: memory-refresh
description: >-
  Maintain and repair the memory wiki. Runs automated lint scripts, builds a
  list of issues needing attention, presents them to the user interactively,
  and executes approved fixes. Handles: todo status updates, frontmatter
  normalisation, broken links, index drift, conflict resolution, and
  USER_STATUS.md tracking.
  Canonical source for both DAGI subagents and Claude Code skills.
---

# memory-refresh

## Purpose

Maintain the memory wiki's structural integrity and content freshness. This
skill combines **automated Python lint scripts** (deterministic checks) with
**agent-driven interactive triage** (the agent presents issues, the user
decides, the agent executes).

---

## Memory Root

```
{memory_root} = G:\My Drive\black_grimoire\dagi-memory
```

---

## Interface

| Parameter | Required | Description |
|-----------|----------|-------------|
| `scope` | no | Narrows to a category, project, or topic (default: full wiki). Examples: `todos`, `projects/dagi`, `knowledge/trading-strategies` |
| `custom_instructions` | no | Freeform guidance |

---

## Scripts Location

Lint scripts live alongside this SKILL.md:

```
.dagi/skills/memory-refresh/scripts/
├── _common.py               ← shared utilities (WIKI_ROOT, parse_frontmatter, etc.)
├── lint_frontmatter.py       ← validate required fields per category
├── verify_links.py           ← check bidirectional wikilinks
├── scan_overdue_todos.py     ← find todos with passed deadlines
└── check_indexes.py          ← verify .index.md tables match folder contents
```

Each script accepts an optional scope argument and outputs a JSON array of
issue objects to stdout:

```json
[
  {
    "file": "todos/todo_002_hdb-flat.md",
    "type": "overdue_todo",
    "message": "Overdue by 12 day(s): deadline was 2026-07-27",
    "severity": "warning"
  }
]
```

---

## Protocol Steps

### Step 1 — Automated sweep

Run each lint script, passing the scope if provided:

```bash
conda run -n dagi python .dagi/skills/memory-refresh/scripts/lint_frontmatter.py [scope]
conda run -n dagi python .dagi/skills/memory-refresh/scripts/verify_links.py [scope]
conda run -n dagi python .dagi/skills/memory-refresh/scripts/scan_overdue_todos.py [scope]
conda run -n dagi python .dagi/skills/memory-refresh/scripts/check_indexes.py [scope]
```

Collect all JSON output into a unified issue list.

### Step 2 — Agent observations

Beyond the script output, scan the wiki for issues that require judgment:

- Suspected stale or outdated content
- Potential contradictions between pages
- Misclassified nodes (e.g. a knowledge page that should be a project)
- Legacy frontmatter fields that should be normalised (`date_added` → `date_created`,
  remove `type`/`topic` fields, promote body wikilinks to `links` field)

Add these to the issue list with source `"agent"`.

### Step 3 — Present to user

Group issues by type and present them to the user. For each issue:

- State the file, the problem, and the severity
- Recommend an action (fix frontmatter, mark todo done, rebuild index, etc.)
- Ask the user to approve, modify, or skip

Use the appropriate interaction tool for the runtime:
- Claude Code: `AskUserQuestion` tool
- DAGI: direct conversation

### Step 4 — Execute approved changes

For each approved action:

- **Frontmatter fix**: read file, update YAML frontmatter, write back
- **Mark todo**: update `status` field in frontmatter
- **Rebuild index**: regenerate `.index.md` table from actual folder contents
- **Fix broken link**: remove or update the wikilink
- **Normalise legacy fields**: rename `date_added` → `date_created`, remove
  `type`/`topic`, promote body wikilinks to `links`
- **Supersede contradiction**: mark old content as superseded with dated
  annotation, link to replacement

### Step 5 — Log changes

Append one line per modification to `wiki/log.md`:

```
[{YYYY-MM-DD}] refresh | {description} | {file path}
```

---

## Additional Responsibilities

### USER_STATUS.md tracking (moved from memory-add)

During the refresh scan, assess whether any USER_STATUS.md updates are
warranted based on recent wiki activity:

- **Knowledge state**: gaps, covered concepts, demonstrated strengths per topic
- **Communication notes**: actionable lessons for working with the Admiral

Update `wiki/USER_STATUS.md` only when a genuine signal is present. Most
refreshes won't touch it.

### Frontmatter normalisation (gradual migration)

Detect legacy frontmatter patterns and offer to normalise:
- `date_added` → `date_created`
- Remove `type` field (category inferred from folder)
- Remove `topic` field (inferred from folder)
- Remove `source` field
- Add missing `links` field (promote body `[[wikilinks]]` to frontmatter)
- Add missing `title` (derive from `# heading` or filename)

---

## Guidelines

- Never auto-fix without user approval — present and wait
- Group issues for efficient review (all frontmatter issues together, etc.)
- Prioritise: overdue todos first, then broken links, then stale content
- Designed for future scheduled/cron execution — keep the protocol stateless
  and idempotent
