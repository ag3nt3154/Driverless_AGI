---
name: memory-add
description: Core wiki-writing primitive — integrate a piece of text into the wiki (topic routing, node creation, index updates, log). Called directly for user-typed content or by memory-ingest for file sources.
triggers: save to memory, add to wiki, remember this, store in memory, add to memory, write to wiki, note this down
---

# memory-add — Add Content to the Wiki

## Path Roots

All paths in this skill are under **memory root** (`{memory_root}`), NOT under CWD (`{cwd}`).
The `read`, `write`, `edit`, and `find` tools resolve from CWD — use **bash with absolute paths** for all file I/O:

- Read: `bash: type "{memory_root}\wiki\{path}"`
- Write/append: `bash: ... | Out-File -FilePath "{memory_root}\wiki\{path}" -Encoding utf8`
- List: `bash: dir "{memory_root}\wiki\{topic}"` (use `dir`, not `ls`, on non-C: drives)
- Grep across wiki: use the `grep` tool — it accepts absolute paths

---

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

Check `{memory_root}/wiki/index.md` exists using `find`. If not, stop:
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
- Topic-level: `{memory_root}/wiki/{topic}/{slug}.md`
- Sub-topic: `{memory_root}/wiki/{topic}/{subtopic}/{slug}.md`

---

## Step 4 — Check existing wiki state

**4a.** `read {memory_root}/wiki/index.md` — does the topic already exist?

**4b.** If topic exists: `read {memory_root}/wiki/{topic}/index.md` — scan for
related pages and sub-topics.

**4c.** For each significant entity from Step 2, check for an existing page:
`grep "{entity name}" {memory_root}/wiki/**/*.md`
Note which entities already have pages (to update) vs. which are new (to create).

---

## Step 4.5 — Decide: single node or split?

Before writing, analyse the content for natural idea breakpoints.

A **distinct idea** qualifies for its own node if it:
- Has its own premise and conclusion (can stand alone)
- Could be understood without the other ideas in the source
- Is likely to be referenced or searched independently in the future

**If single idea:** proceed to Step 5 with one node.

**If multiple distinct ideas:** list them explicitly before writing (e.g. "Idea 1: X, Idea 2: Y"). Then write one node per idea, running Step 5 for each in sequence. Assign each node its own descriptive slug (e.g. `attention-mechanism-self-attention`, `attention-mechanism-multi-head`) rather than `part-1`, `part-2` suffixes where possible.

**Linking split nodes:** every node in a split set must include a "Part of series" block in its Related Pages section:

```markdown
## Related Pages

**Part of series:** {source title or unifying theme}
- [[{topic}/{sibling-slug-1}]] — {one phrase: what that node covers}
- [[{topic}/{sibling-slug-2}]] — {one phrase}
- [[{topic}/index]] — parent topic
```

**When NOT to split:**
- A unified list of facts or tips on one subject (keep together)
- Ideas that are tightly interdependent and lose meaning when separated
- Input shorter than 3 paragraphs — splitting would produce stub nodes

---

## Step 5 — Write the wiki node

Write the wiki node at the path determined in Step 3 (or per-idea paths if split).

**Writing standard:** Write as if the source will never be consulted again. A reader
must be able to fully understand the subject — including background, reasoning,
evidence, and implications — from this node alone. Depth scales with input richness:
a brief personal note may be 2–3 paragraphs; a dense paper or technical document
should be as long as needed to capture it completely. Do not compress: if the source
spends significant space on a mechanism or example, so should the wiki node.

Omit sections the input has no material for — never invent content to fill a section.

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

---

### Body template — `info` content

Use for facts, research findings, technical knowledge, how-tos, and external sources.

```markdown
# {Descriptive title}

{ingest mode only — omit in direct mode:}
> Source: [{filename}]({relative path from wiki node to archive}) | Added: YYYY-MM-DD

## Background

{Why does this topic exist or matter? What problem does it solve, or what context
is needed to understand it? 1–3 paragraphs. Include historical or domain context
if present in the source.}

## Core Concepts

{Define every key term used in this content. Use bold term + colon format.
Include the definition as it applies in this specific context, not just a generic one.}

**{Term}**: {Definition.}
**{Term}**: {Definition.}

## How It Works

{The full mechanism, process, or explanation. Preserve specific steps, causal chains,
and logical structure. If the source has 5 steps, capture all 5 with their detail.
Use numbered lists for sequential processes, prose for causal explanations.}

## Evidence & Examples

{Specific data points, case studies, worked examples, or experiments that support
the claims. Include numbers, names, dates, and sources where present. Vague
references ("studies show") are not sufficient — name the study if known.}

## Implications & Applications

{What does this mean in practice? How can it be applied? What does it change about
how to think about related topics or adjacent fields?}

## Limitations & Caveats

{What does this NOT apply to? What assumptions does it rest on? What are known
failure modes, open debates, or contested claims?}

## Related Pages

- [[{topic}/index]] — parent topic
- [[{related-topic}/{related-page}]] — {why related, one phrase}
```

---

### Body template — `thought` content

Use for reflections, opinions, hypotheses, plans, and personal observations.

```markdown
# {Descriptive title}

## Context & Premise

{What prompted this thought? What situation, observation, or prior belief is it
responding to? What assumptions does it start from?}

## The Argument

{The full reasoning chain. Preserve the logic, not just the conclusion. If there
are sub-points or steps in the reasoning, list them with their supporting logic.
Do not flatten a multi-step argument into a single conclusion.}

## Supporting Evidence or Examples

{What does this thought draw on? References, analogies, personal experiences, or
prior observations cited. Be specific about what evidence supports which claim.}

## Conclusions

{What does this lead to? What action, belief, or further question does it produce?
State both the immediate conclusion and any second-order implications.}

## Open Questions

{What does this thought leave unresolved? What evidence would change the conclusion?
What needs to be investigated before acting on this?}

## Related Pages

- [[{topic}/index]] — parent topic
- [[{related-topic}/{related-page}]] — {why related, one phrase}
```

---

The templates are a starting point, not a rigid requirement. Add, rename, or merge
sections to fit the content — a short personal note may only need Context, Argument,
and Conclusions; a technical deep-dive may add Methodology or Worked Examples.

---

## Step 6 — Create or update entity/concept pages

**If the content was split in Step 4.5:** collect entities from ALL nodes first, then
process entity pages once — do not create duplicate entity pages for the same entity
appearing in multiple sibling nodes. Each entity page's `## Sources` section should
reference all sibling nodes that mention it.

For each **significant entity** identified in Step 2:

**Entity already has a page** (found via grep in Step 4c):
1. `read` the existing page
2. Add new information from this content using `edit`
3. Append to the page's `## Sources` section (create it if absent):
   `- [[{topic}/{slug}]] — {one sentence on what this content adds about this entity}`
4. Update `last_updated` in frontmatter to today

**No page exists yet** and the entity is significant enough to warrant one:
Create `{memory_root}/wiki/{topic}/{EntityName}.md`:

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

**Topic index.md** — `{memory_root}/wiki/{topic}/index.md`:

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

**Root index.md** — `{memory_root}/wiki/index.md`:

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

For `direct` mode: `read {memory_root}/wiki/log.md`, then `edit` to append:

```markdown
## [YYYY-MM-DD] add | {slug} {or: slug-1, slug-2, ... if split}
- Topic: {topic}{/subtopic if applicable}
- Wiki nodes: {memory_root}/wiki/{topic}/{slug}.md {list all if split}
- Pages created: {comma-separated list, or "none"}
- Pages updated: {comma-separated list, or "none"}
```

---

## Step 9 — Update overview.md (conditional)

`read {memory_root}/wiki/overview.md`.

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
1. `read {memory_root}/wiki/open_questions.md`
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
- Wiki nodes created: `{path}` (list all if split — one line per node)
- Split into N nodes: `{yes/no — if yes, briefly explain the breakpoints chosen}`
- Entity/concept pages created: `{list or "none"}`
- Pages updated: `{list or "none"}`
- index.md files updated: `{list}`
- Open question(s) added to open_questions.md: `"{question text}"` (one per node if split)
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
