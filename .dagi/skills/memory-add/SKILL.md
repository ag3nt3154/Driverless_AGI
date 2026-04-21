---
name: memory-add
description: Core wiki-writing primitive — integrate a piece of text into the wiki (topic routing, node creation, index updates, log). Called directly for user-typed content or by memory-ingest for file sources.
---

# memory-add — Add Content to the Wiki

## Purpose

This is the core wiki-writing operation. It takes a piece of text and integrates
it into the wiki: determines the topic, creates a wiki node, creates or updates
related entity/concept pages, and keeps all index.md files current.

**Two calling modes:**

| Mode | Triggered by | Log entry | Archive link |
|------|-------------|-----------|--------------|
| `direct` | User types text in CLI | Written here (operation: `add`) | None |
| `ingest` | Called from `memory-ingest` | Written by memory-ingest (skip here) | Provided by caller |

The caller sets the mode by telling you which applies before you start.
If no mode is specified, assume `direct`.

---

## Step 1 — Confirm the wiki is initialised

Check `dagi-memory/wiki/index.md` exists using `find`. If not, stop:
"Run `/init` first."

---

## Step 2 — Understand the content and assign tags

Read the input text carefully. Identify:

1. **Main subject** — what is this primarily about?
2. **Named entities** — people, organisations, tools, events, concepts worth a page
3. **Key claims or insights** — what does this assert or reveal?
4. **Connections** — what in the wiki might this relate to?

Then assign two tags based on the content itself (not the calling mode):

**Tag 1 — `info` or `thought`**

| Tag | Assign when… |
|-----|-------------|
| `info` | Content presents facts, data, research findings, established knowledge, or how-tos from an external or authoritative source |
| `thought` | Content is the user's own reflection, opinion, hypothesis, plan, brainstorm, or personal observation — even if it cites facts |

When in doubt: if the primary value of the note is the *idea or perspective*, use `thought`. If it's the *information itself*, use `info`.

**Tag 2 — `human` or `ai`**

| Tag | Assign when… |
|-----|-------------|
| `human` | Content originated from a human — user-typed text, external articles, papers, books, notes |
| `ai` | Content was generated or researched by dagi (reserved for future autonomous research nodes) |

Currently all content is `human` unless the caller explicitly states otherwise.

---

## Step 3 — Determine topic, sub-topic, and slug

1. **Topic** — primary subject area, kebab-case, 1–3 words.
   Examples: `llm-agents`, `knowledge-management`, `personal`, `python-tooling`

2. **Sub-topic** (optional) — narrower category within the topic. Only assign one if
   the topic folder already has sub-folders and this content clearly belongs in one.
   When in doubt, place at the topic level.

3. **Slug** — short kebab-case page identifier derived from the main subject.
   Examples: `vannevar-bush-memex`, `tool-use-patterns`, `reflection-2026-04-18`
   If a file already exists at the target path, append `-2`, `-3`, etc.

**Target path:**
- Topic-level: `dagi-memory/wiki/{topic}/{slug}.md`
- Sub-topic: `dagi-memory/wiki/{topic}/{subtopic}/{slug}.md`

---

## Step 4 — Check existing wiki state

**4a.** `read dagi-memory/wiki/index.md` — does the topic already exist?

**4b.** If topic exists: `read dagi-memory/wiki/{topic}/index.md` — scan for
related pages and sub-topics.

**4c.** For each significant entity from Step 2, check for an existing page:
`grep "{entity name}" dagi-memory/wiki/**/*.md`
Note which entities already have pages (to update) vs. which are new (to create).

---

## Step 5 — Write the wiki node

Write the wiki node at the path from Step 3.

**Frontmatter:**
```yaml
---
type: note
topic: {topic}
tags:
  - {info or thought}
  - {human or ai}
date_added: YYYY-MM-DD
source: {archive path — only if ingest mode, omit if direct}
---
```

Adjust `type` to fit: `note` (default), `source-summary`, `reflection`, `insight`,
`analysis`. Use judgment based on the content.

**Body template:**
```markdown
# {Descriptive title}

{ingest mode only — omit in direct mode:}
> Source: [{filename}]({relative path from wiki node to archive}) | Added: YYYY-MM-DD

## Summary

{2–4 paragraph synthesis of the content, written clearly in your own words.
For direct user input: preserve meaning but organise into coherent paragraphs.
For ingested sources: distil the key content, not just list facts.}

## Key Points

- {3–8 bullet points: the most important facts, claims, or insights}

## Related Pages

- [[{topic}/index]] — parent topic
- [[{related-topic}/{related-page}]] — {why related, one phrase}
```

Adapt the structure to the content. A short personal note may only need "Summary".
A dense paper may add "Methodology" or "Conclusions" sections. The template is a
starting point, not a rigid requirement.

---

## Step 6 — Create or update entity/concept pages

For each **significant entity** identified in Step 2:

**Entity already has a page** (found via grep in Step 4c):
1. `read` the existing page
2. Add new information from this content using `edit`
3. Append to the page's `## Sources` section (create it if absent):
   `- [[{topic}/{slug}]] — {one sentence on what this content adds about this entity}`
4. Update `last_updated` in frontmatter to today

**No page exists yet** and the entity is significant enough to warrant one:
Create `dagi-memory/wiki/{topic}/{EntityName}.md`:

```yaml
---
type: entity
topic: {topic}
sources:
  - {topic}/{slug}.md
last_updated: YYYY-MM-DD
---
```

```markdown
# {Entity Name}

{2–3 sentence description based on what this content says.}

## Sources

- [[{topic}/{slug}]] — {what this content says about this entity}
```

**When to create a dedicated page:** the entity is central to this content AND
likely to appear in future additions. Peripheral mentions stay as inline wikilinks
in the wiki node.

---

## Step 7 — Update index.md files

Update every `index.md` in folders touched by this addition.

**Topic index.md** — `dagi-memory/wiki/{topic}/index.md`:

If it does not exist (new topic), create it:
```markdown
# {Topic Name — title-cased, spaces}

> **Last updated:** YYYY-MM-DD

## Sub-topics
| Folder | Description |
|--------|-------------|
| — | — |

## Pages in this folder
| Page | Summary | Tags | Last Updated |
|------|---------|------|--------------|
| [[{slug}]] | {one-line summary of wiki node} | {info or thought} · {human or ai} | YYYY-MM-DD |
```

If it exists, `read` it first, then `edit`:
- Add row to "Pages in this folder": `| [[{slug}]] | {summary} | {info or thought} · {human or ai} | YYYY-MM-DD |`
- Replace `| — | — |` placeholder if still present (use `| — | — | — | — |` to include Tags column)
- Update `> **Last updated:**` date
- If a new sub-topic was used, add a row to "Sub-topics"
- If the existing table header lacks a Tags column, add it with `edit` before inserting the new row

**Root index.md** — `dagi-memory/wiki/index.md`:

`read` it first, then `edit`:
- New topic: add row `| [{topic}/](wiki/{topic}/index.md) | {one-line description} | 1 | YYYY-MM-DD |`
- Existing topic: increment Pages count, update Last Updated
- Replace `| — | — | — | — |` placeholder if present

**Sub-topic index.md** (if applicable): create or update the same way as topic index.

If any index.md is approaching 50 rows, note this in your final reply — the user
may want to run `memory-lint` to consider a sub-topic split.

---

## Step 8 — Append to log.md (direct mode only)

**Skip this step entirely if called from `memory-ingest`.** The caller handles log.

For `direct` mode: `read dagi-memory/wiki/log.md`, then `edit` to append:

```markdown
## [YYYY-MM-DD] add | {slug}
- Topic: {topic}{/subtopic if applicable}
- Wiki node: dagi-memory/wiki/{topic}/{slug}.md
- Pages created: {comma-separated list, or "none"}
- Pages updated: {comma-separated list, or "none"}
```

---

## Step 9 — Update overview.md (conditional)

`read dagi-memory/wiki/overview.md`.

Update **only** if this content adds synthesis-level value:
- A new theme that connects previously separate topics
- A major claim that changes the overall picture
- A contradiction or refinement of a prior synthesis claim

If overview still reads `_No sources ingested yet._` and this is a substantive
addition, replace it with a short opening paragraph summarising the emerging picture.

If nothing synthesis-level applies, skip this step.

---

## Step 10 — Generate and append one open question

Derive ONE open question from the content just added. The question should:
- Be **relevant to the topic** but **not directly answered** by the wiki node you just created
- Represent a genuine research gap, next investigation, or unverified claim raised by the content
- Be concrete and actionable — not "what else is there?" but specific enough to research

**Do not generate:**
- Questions trivially answered within the node itself
- Generic curiosity questions ("what more can be learned about this topic?")
- Questions already present in the Pending table

**Process:**
1. `read dagi-memory/wiki/open_questions.md`
2. Count existing Pending rows (exclude placeholder). Assign next sequential number N.
3. Append to the Pending table:
   `| {N} | {Question} | {One-sentence context} | [[{topic}/{slug}]] | {YYYY-MM-DD} |`
4. Replace placeholder `| — | — | — | — | — |` if still present in the Pending section.
5. Update `> **Last updated:**` date.

If `open_questions.md` does not exist (wiki initialised before this feature was added),
stop and tell the user: "open_questions.md not found — run `/init` again to create it."

---

## Step 11 — Report

Tell the user:
- Wiki node created at: `{path}`
- Entity/concept pages created: `{list or "none"}`
- Pages updated: `{list or "none"}`
- index.md files updated: `{list}`
- Open question added to open_questions.md: `"{question text}"`
- Any index.md approaching 50 rows (if applicable)

---

## Edge Cases

- **Wiki not initialised:** Stop at Step 1. Run `/init` first.
- **Slug already exists:** Append `-2`, `-3`, etc.
- **`edit` oldText not unique:** Expand surrounding context to uniquify. If still not
  possible, append to the end of the relevant section.
- **Very short input (< 2 sentences):** Ask the user if they want to elaborate before
  adding. A very short note is fine if that's what the user intends.
- **Ambiguous topic:** Pick the most specific plausible topic. Note the choice in
  your report so the user can redirect if needed.
- **Entity page creation ambiguity:** When unsure whether an entity warrants its own
  page, default to leaving it as an inline wikilink. Create the page on the next
  addition that also mentions it.
