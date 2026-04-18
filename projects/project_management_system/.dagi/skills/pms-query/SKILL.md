---
name: pms-query
description: Answer questions about the project by reading the wiki and tracing back to source documents
---

# pms-query — Query the Project Wiki

## Purpose

Answer questions about the project by consulting the wiki documents. Use this skill
whenever the user asks about project status, tasks, features, decisions, deliverables,
schedules, or anything that may be recorded in the wiki.

Do not answer from memory or make up information — ground every answer in what the
wiki actually contains.

---

## Step 1 — Parse the query

Before opening any files, identify:

1. **Query type** — Is this asking about one of the following?
   - Schedule, tasks, or deadlines
   - Features, architecture, or use case
   - Decisions made
   - Deliverables or stakeholder requests
   - Open questions or unknowns
   - A specific source document
   - A cross-document question (e.g. "what features are behind schedule?")

2. **Key entities** — Extract any named items: feature names, dates, people, milestones,
   deliverable names.

3. **Scope** — Is this a single-document lookup, or does answering it require correlating
   information across multiple wiki documents?

---

## Step 2 — Determine which documents to read

Use this routing table as your starting point:

| If the query is about… | Start with… |
|------------------------|-------------|
| Tasks, deadlines, milestones | `wiki/schedule.md` |
| Features, architecture, use case | `wiki/readme.md` |
| Deliverables, stakeholder requests | `wiki/deliverables.md` |
| Decisions made | `wiki/decisions.md` |
| Unknowns, gaps, pending clarifications | `wiki/open_questions.md` |
| Which source file contains what | `wiki/index.md` |
| Cross-document / unclear scope | Start with `wiki/index.md` to understand coverage |

For cross-document questions, plan which documents to read before opening any of them.

---

## Step 3 — Verify the wiki exists

Before reading, confirm `wiki/readme.md` exists using `find` with pattern
`wiki/*.md` and path `.`. If no wiki files are found, stop and tell the user:
"The wiki has not been initialised. Run the `pms-init` skill first."

---

## Step 4 — Read the identified documents

Use `read` to load each document in full. Do not use offset/limit unless the file
exceeds 500 lines — in that case, use `grep` with a relevant keyword first to locate
the section, then use `read` with `offset`/`limit`.

After reading each document, note:
- Sections or rows directly relevant to the query.
- Any source links (`[[sources/{type}/filename]]`) that point to original documents
  which may contain more detail.

---

## Step 5 — Follow source links if needed

Only follow a source link when:
- The wiki entry is a brief summary and the user's query requires the original detail
  (e.g. "what exactly did the client say about X?"), OR
- The wiki entry is ambiguous and the source would resolve the ambiguity.

To read a source file: `read wiki/sources/{type}/{filename}`

Do not read source documents by default for every query — the wiki summaries are
usually sufficient.

---

## Step 6 — Correlate for cross-document queries

For queries that span multiple documents, build the cross-reference manually.

**Example — "what features are behind schedule?":**
1. Read `wiki/readme.md` → extract all rows from the Features table.
2. Read `wiki/schedule.md` → find tasks whose Due date has passed (compare against
   today's date) or are marked overdue.
3. Match feature names from readme.md against task descriptions in schedule.md.
4. Report the intersection.

**Example — "are there unresolved questions about deliverables?":**
1. Read `wiki/deliverables.md` → extract open deliverables.
2. Read `wiki/open_questions.md` → scan Pending questions for mentions of those items.
3. Report matching entries.

**Example — "what has been ingested so far?":**
1. Read `wiki/index.md` → summarise all rows in the source table.

When comparing dates against today, use the current date from the system or ask the
user if uncertain.

---

## Step 7 — Compose the answer

Structure your response in three parts:

### Part 1 — Direct Answer

Answer the user's question in plain language. Be concise (2–5 sentences). If the
information is not in the wiki, say so explicitly — do not invent or infer answers.

### Part 2 — Relevant Wiki Sections

Quote the specific rows, task items, or paragraphs from the wiki that support your
answer. Preserve original formatting (tables, task list checkboxes). Label each
excerpt with its source document:

> **From `wiki/schedule.md`:**
> - [ ] Build authentication module — Due: 2025-06-15 | [[sources/emails/kickoff.eml]]

Include only the sections directly relevant to the query. Do not dump entire documents.

### Part 3 — Linked Source Documents

List the original source files referenced by the relevant wiki entries. For each:
- Show the path: `wiki/sources/{type}/{filename}`
- Describe what it contains in one sentence.

If no source links appear in the relevant wiki sections, omit Part 3 and note:
"No source documents are linked for this information."

---

## Step 8 — Handle gaps and uncertainty

If the wiki does not contain the information requested:

1. Check `wiki/open_questions.md` — is the gap already flagged as a known unknown?
   If so, surface that entry to the user.

2. Check `wiki/index.md` — is there a source file that was ingested but may contain
   relevant information not yet extracted into the wiki? If so, name it.

3. If neither yields an answer, tell the user:
   "This information is not currently recorded in the wiki. You may want to add a
   relevant source file to `raw/` and run the `pms-ingest` skill."

---

## Edge Cases

- **Query matches nothing:** Follow Step 8. Never fabricate information.
- **Ambiguous query:** Read `wiki/index.md` first to understand what topics are covered.
  Then ask the user a clarifying question listing the candidate topics before reading
  further.
- **Wiki not initialised:** If `wiki/*.md` files do not exist, direct the user to
  run `pms-init`.
- **Source file linked in wiki no longer exists:** Note the broken link to the user.
  Continue answering from the wiki text alone.
- **Conflicting data across documents:** Surface the conflict explicitly. Example:
  "deliverables.md shows Feature X due 2025-06-01, but schedule.md shows the implementing
  task due 2025-08-15. These may be inconsistent — you may want to review both documents."
- **Very large wiki files (>500 lines):** Use `grep` with a keyword to locate the
  relevant section first, then `read` with `offset`/`limit`.
- **User asks for everything on a topic:** Read all six wiki documents, synthesise a
  comprehensive answer, and clearly attribute each fact to its source document.
- **User asks about a source file directly:** Read it from `wiki/sources/{type}/{filename}`
  and summarise its contents along with which wiki documents it updated (from index.md).
