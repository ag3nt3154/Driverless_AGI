---
name: memory-query
description: Answer questions by searching the dagi-memory wiki using both index navigation and grep, then synthesise an answer with citations. Offers to file novel synthesis as a new wiki page via memory-add. Use when the user asks about something that may be in the wiki, wants to recall prior knowledge, or asks "what do I know about X".
---

# memory-query

## Purpose

Answer questions by traversing the wiki's index structure and grepping for relevant content.
Ground every answer in what the wiki contains. Do not answer from training knowledge alone —
state clearly when wiki evidence is absent.

---

## Step 0 — Resolve memory root

1. Attempt to read `{cwd}/config.yaml`.
2. If it exists and contains a non-empty, uncommented `memory_root:` key, use that value.
   Strip surrounding quotes and trailing slashes.
3. Otherwise fall back to `{cwd}/dagi-memory`.
4. If the resolved path differs from the default, note it briefly.

All subsequent paths are relative to `{memory_root}`.

---

## Wiki Structure

```
{memory_root}/
└── wiki/
    ├── .index.md              ← root nav — lists Projects and Knowledge sections
    ├── log.md
    ├── open_questions.md
    ├── projects/
    │   ├── .index.md          ← table of all tracked projects
    │   └── {project-name}/
    │       ├── .index.md      ← project page index
    │       └── *.md
    └── knowledge/
        ├── .index.md          ← table of all knowledge topics
        └── {topic}/
            ├── .index.md      ← topic page index
            └── *.md
```

All page frontmatter follows this schema:
```yaml
---
type: note | entity | source-summary | reflection | insight | analysis | context | update
topic: {topic-name}     # or project/{project-name} for project pages
description: one-line summary
date_added: YYYY-MM-DD
tags: keyword1, keyword2, keyword3
---
```

---

## Step 1 — Scan injected wiki indexes

The wiki index is injected into every session as `[WIKI INDEX]` in the system prompt.
If it is not sufficient (e.g. first query of session, or you need per-topic indexes),
read them explicitly:
```
read("{memory_root}/wiki/.index.md")
read("{memory_root}/wiki/projects/.index.md")
read("{memory_root}/wiki/knowledge/.index.md")
```

---

## Step 2 — Grep for key terms

Extract the most specific terms from the query (entity names, technical terms, project names).

**grep the likely section first:**
```
grep(pattern="<term>", path="{memory_root}/wiki/knowledge/")
# or
grep(pattern="<term>", path="{memory_root}/wiki/projects/")
```

If fewer than 3 hits, widen to the full wiki:
```
grep(pattern="<term>", path="{memory_root}/wiki/")
```

Rank candidate pages by grep hit density (number of matching lines). Run multiple grep
passes for different key terms if the first yields sparse results.

---

## Step 3 — Read candidates

For the top 3–5 candidates:
1. Read the page.
2. If the page contains `[[wikilinks]]` to related pages, read those too if they are relevant.
3. If a topic or project `.index.md` is relevant, read it to discover other pages in that
   folder that did not surface in the grep.

---

## Step 4 — Synthesise and report

Compose an answer that:
- Directly addresses the query.
- Cites each wiki page used: `[knowledge/topic/slug.md]` or `[projects/name/page.md]`.
- Notes any gaps: "The wiki does not contain information about X."
- Suggests filing a new wiki page if the synthesised answer is novel and reusable.

Report inline. Example format:

```
## Answer

{synthesised answer with inline citations}

## Sources

- knowledge/machine-learning/bias-variance.md — definition and decomposition
- knowledge/statistics/probability-theory.md — supporting probability background

## Gaps

The wiki has no pages on {X}. Would you like me to file a note on this?
```

---

## Guidelines

- Do not answer from training knowledge without wiki grounding — state clearly when wiki
  evidence is absent.
- Prefer specificity: a precise answer citing 2 pages beats a vague one citing 10.
- If the injected indexes are sufficient to answer the query without further reads, do so —
  keep tool calls lean.
- If the query matches a project (starts with "Project: <name>" or clearly refers to a
  tracked project), scan `wiki/projects/<name>/` first, reading `context.md` and
  `updates.md` before grepping for sub-pages.
- If the wiki is not initialised (`wiki/.index.md` missing), stop and tell the user.
