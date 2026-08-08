---
name: memory-query
description: >-
  Search the memory wiki and synthesise an answer with citations. Subagent
  protocol — strictly read-only. The parent agent passes a question and
  optional scope; this skill navigates indexes, greps for terms, reads
  candidates, and returns a grounded answer.
  Canonical source for both DAGI subagents and Claude Code skills.
---

# memory-query

## Purpose

Answer questions by traversing the memory wiki's index structure and grepping
for relevant content. Ground every answer in what the wiki contains. State
clearly when wiki evidence is absent. **Strictly read-only** — never write to
the wiki.

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
| `task` | yes | The question or topic to look up |
| `scope` | no | Narrows search to a subtree (e.g. `todos`, `projects/dagi`, `knowledge/trading-strategies`) |
| `custom_instructions` | no | Freeform guidance from parent |

---

## Wiki Structure

```
wiki/
├── .index.md
├── projects/   ← bounded initiatives
├── todos/      ← actionable items
├── knowledge/  ← durable domain expertise
└── events/     ← life events, decisions, conversations
```

Each section and sub-folder has a `.index.md` with a table of its children.

---

## Protocol Steps

### Step 1 — Load indexes

Read the root and section indexes to orient:

```
read("wiki/.index.md")
read("wiki/projects/.index.md")
read("wiki/todos/.index.md")
read("wiki/knowledge/.index.md")
read("wiki/events/.index.md")
```

If `scope` is provided, only load the scoped section's index.

Use these to identify candidate sections and likely topics relevant to the
query before grepping.

### Step 2 — Grep for key terms

Extract the most specific terms from the query (entity names, technical terms,
project names).

Grep the most likely section first (based on Step 1's candidates):

```
grep("<term>", path="wiki/{likely-section}/")
```

If `scope` is provided, search only within that subtree.

If fewer than 3 hits in the scoped section, widen to the full wiki:

```
grep("<term>", path="wiki/")
```

Rank candidate pages by grep hit density (number of matching lines). Run
multiple grep passes for different key terms if the first yields sparse
results.

### Step 3 — Read candidates

For the top 3–5 candidates:

1. Read the page
2. If the page contains `[[wikilinks]]` to related pages, read those too if
   relevant
3. If a topic or project `.index.md` is relevant, read it to discover other
   pages in that folder that did not surface in the grep

### Step 4 — Synthesise and report

Compose an answer that:
- Directly addresses the query
- Cites each wiki page used with `[[wikilinks]]`
- Notes any gaps: "The wiki does not contain information about X"
- Suggests filing a new wiki page via memory-add if the synthesised answer
  is novel and reusable

---

## Handoff (subagent → parent)

```
## Answer

{synthesised answer with [[wikilink]] citations}

## Sources

- {wiki/path/to/page.md} — {one-line reason it was relevant}

## Gaps

{relevant topics not found in the wiki, or "None identified"}

## Suggestions

{if synthesis is novel: "Consider filing via memory-add: {brief description}"}
{otherwise: "None"}
```

---

## Guidelines

- Do not answer from training knowledge without wiki grounding — state
  clearly when wiki evidence is absent
- Prefer specificity: a precise answer citing 2 pages beats a vague one
  citing 10
- If the indexes are sufficient to answer the query without reading every
  page, do so — keep tool calls lean
- If the query matches a project, scan `wiki/projects/{name}/` first,
  reading `overview.md` before grepping for sub-pages
- If the wiki is not initialised (`wiki/.index.md` missing), state this in
  the handoff and stop
- **Never write to the wiki.** Suggest memory-add in the handoff if
  appropriate; the parent decides

## Coding Standards

- Files ≤ 500 lines
- Line length ≤ 100 chars
