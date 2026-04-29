---
name: memory-query
description: Answer questions by traversing the dagi wiki index hierarchy, then offer to file the answer as a new wiki page
---

# memory-query — Query the Dagi Wiki

## Path Roots

All paths in this skill are under **memory root** (`{memory_root}`), NOT under CWD (`{cwd}`).
Use bash with absolute paths for all file I/O — `read`/`write`/`edit`/`find` resolve from CWD and will fail.
Use `dir` not `ls` on non-C: drives.

---

## Purpose

Answer questions by consulting the wiki at `{memory_root}/wiki/`. Navigate the
index.md hierarchy to find relevant pages, synthesise an answer with citations,
and offer to file the answer as a new wiki page if it adds value.

Do not answer from memory alone — ground every answer in what the wiki contains.
If information is not in the wiki, say so explicitly and suggest how to add it.

---

## Step 1 — Parse the query

Before opening any files, identify:

1. **Key terms and entities** — extract named things, concepts, or questions in the query.
2. **Likely topics** — which topic areas are probably relevant?
3. **Scope** — single-page lookup, or cross-topic synthesis?

---

## Step 2 — Verify the wiki exists

Use `find` with pattern `index.md` and path `{memory_root}/wiki/` to confirm the
wiki has been initialised. If not found, stop and tell the user:
"The wiki has not been initialised. Run `/init` first."

---

## Step 3 — Navigate via root index.md (semantic routing)

`read {memory_root}/wiki/index.md`

Scan the topic table for entries whose description matches the query's key terms or
likely topic areas. Identify candidate topic folders to drill into.

If the root index has no entries yet, skip to Step 5 (grep fallback).

---

## Step 4 — Drill into topic index.md files

For each candidate topic identified in Step 3:

`read {memory_root}/wiki/{topic}/index.md`

Scan "Sub-topics" and "Pages in this folder" for entries relevant to the query.
Identify specific pages to read.

If a sub-topic looks relevant, read its index.md too:
`read {memory_root}/wiki/{topic}/{subtopic}/index.md`

Limit depth: stop at the first level that surfaces specific page names.

---

## Step 5 — grep fallback (if index routing fails)

If Steps 3–4 do not surface relevant pages, use grep:

`grep "{key term}" {memory_root}/wiki/**/*.md`

This finds pages containing the exact term even when index.md summaries don't match.
Collect matching file paths.

Use grep sparingly — it returns raw matches without semantic context. Use it to
locate pages, then read those pages for context.

---

## Step 6 — Read relevant pages

`read` each relevant page identified in Steps 3–5.

After reading each page, note:
- Key facts, claims, or insights relevant to the query.
- Inline wikilinks to related pages — follow these if the linked page is likely to
  add important context.
- `source:` frontmatter field — path to the original archived source.

Limit link-following to 1–2 hops. Do not traverse the entire wiki.

---

## Step 7 — Read source documents if needed

Only read the original archived source when:
- The wiki node is a high-level summary and the query requires specific detail
  (e.g. "what exactly did the paper say about X?"), OR
- The wiki node is ambiguous and the source would resolve it.

Path: `{memory_root}/sources/{topic}/{filename}`

Do not read sources by default — wiki nodes are usually sufficient.

---

## Step 8 — Cross-topic synthesis (if needed)

For queries spanning multiple topics:

1. List all relevant pages found across topics.
2. Read them in order of likely relevance.
3. Build the cross-reference manually: match entities, compare claims, note
   contradictions or connections.
4. Surface any contradictions explicitly rather than silently choosing one.

---

## Step 9 — Compose the answer

Structure your response as follows:

### Part 1 — Direct Answer

Answer in plain language (2–6 sentences). If the wiki does not contain the
information, say so — do not invent or extrapolate.

### Part 2 — Evidence from the Wiki

Quote or paraphrase the specific passages, table rows, or bullet points that
support the answer. Label each excerpt with its page path:

> **From `{memory_root}/wiki/knowledge-management/pioneers/VannevarBush.md`:**
> VannevarBush proposed the Memex in 1945 — a personal knowledge device with
> associative trails between documents.

Include only the directly relevant sections. Do not dump full pages.

### Part 3 — Source Documents

List the archived sources referenced by the wiki pages used in your answer:
- Path: `{memory_root}/sources/{topic}/{filename}`
- One-sentence description of what it contains.

Omit Part 3 if no source links appear in the relevant wiki sections.

---

## Step 10 — Handle missing information

If the wiki does not contain the answer:

1. Check `wiki/log.md` — was a related source ingested but perhaps not fully
   extracted? Name it so the user can investigate.
2. Tell the user what is missing and suggest adding a source to `raw/` and
   running `memory-ingest`.
3. If the query reveals a gap worth tracking, offer to add it as a note to the
   relevant topic's index.md.

---

## Step 11 — Offer to file the answer as a new wiki page

After answering, assess whether the answer itself adds value as a wiki page:

File if:
- The answer synthesises information from multiple pages in a novel way.
- The query and answer constitute a reusable reference (e.g. "how does X relate
  to Y?", "what are all the tools for Z?").
- The answer would prevent the same research from being repeated next session.

Do not file if:
- The answer is a direct lookup with no synthesis (already in a page).
- The answer is ephemeral or session-specific.

If filing is warranted, ask the user:
"This answer involves useful synthesis. Shall I file it as a new page at
`{memory_root}/wiki/{topic}/{suggested-slug}.md`?"

If the user agrees, write the page, update the topic index.md, and append to log.md:
```markdown
## [YYYY-MM-DD] query | "{query summary}"
- Topics consulted: {list}
- Answer filed as: {memory_root}/wiki/{topic}/{slug}.md
```

If not filing, still append to log.md:
```markdown
## [YYYY-MM-DD] query | "{query summary}"
- Topics consulted: {list}
- Answer not filed
```

---

## Edge Cases

- **Query matches nothing in index or grep:** Follow Step 10. Never fabricate.
- **Ambiguous query:** Read root index.md, list candidate topics, ask the user to
  clarify before drilling deeper.
- **Conflicting information across pages:** Surface the conflict explicitly. Do not
  silently prefer one source over another.
- **Very large page (>500 lines):** Use `grep` with a keyword to locate the relevant
  section, then `read` with `offset`/`limit`.
- **Broken source link (source file not found):** Note it to the user. Continue
  answering from the wiki node text alone.
- **Root index.md empty:** Skip to grep fallback (Step 5).
