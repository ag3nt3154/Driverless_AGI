---
name: memory-lint
description: Health-check the dagi wiki — find orphans, broken links, non-compliant nodes, and stale index entries. Remediates format issues, fills gaps via web research, and answers one open question.
---

# memory-lint — Wiki Health Check & Remediation

## Path Roots

All paths in this skill are under **memory root** (`{memory_root}`), NOT under CWD (`{cwd}`).

The `Read`, `Write`, `Edit`, `Grep`, and `Glob` tools all accept **absolute paths** and work
with any location on the filesystem, including `{memory_root}` even when it differs from CWD
or the dagi root. Use them directly:

| Operation | Tool |
|-----------|------|
| Read a file | `Read` with absolute path |
| Write/overwrite a file | `Write` with absolute path |
| Edit a file in-place | `Edit` with absolute path |
| Search file contents | `Grep` with `path: {memory_root}/wiki/` |
| Find files by pattern | `Glob` with `path: {memory_root}/wiki/` |

Use **bash** only for operations the tools cannot do:
- Create directories: `bash: mkdir -p "{memory_root}/wiki/projects/{topic}"`
- List a directory on a non-C: drive: `bash: dir "{memory_root}\wiki\projects"`

---

## Purpose

Audit the wiki at `{memory_root}/wiki/` and produce a prioritised action list.
Run periodically (e.g. after every 5–10 memory-add operations) to keep the wiki healthy.

This skill has three phases:
1. **Read phase (Steps 1–7):** Inspect all wiki pages and collect issues.
2. **Remediation phase (Step 8):** Rewrite non-compliant nodes and fill gaps via web research.
3. **Open question phase (Step 9):** Attempt to resolve one pending question.

---

## Step 0 — Resolve the memory root

1. Attempt to read `{cwd}/config.yaml`.
2. If the file exists and contains a non-empty `memory_root:` key that is not
   commented out, use that value as `{memory_root}` for all subsequent steps.
   Strip any surrounding quotes and trailing slashes.
3. If the file does not exist, or `memory_root` is absent, commented out, or empty,
   fall back to `{cwd}/.dagi/memory` as `{memory_root}`.
4. Note the resolved path to the user only if it differs from the default.

---

## Step 1 — Enumerate all wiki pages

Use `find {memory_root}/wiki/ **/*.md` to collect every markdown file.

Categorise by type:
- `.index.md` files — folder navigation indexes
- `log.md`, `open_questions.md` — meta files (root-level)
- All other `.md` files — content pages (wiki nodes, entity pages)

Record the full list. You will use it in every subsequent check.

---

## Step 2 — Check node format compliance

Read every content page (skip `.index.md`, `log.md`, `open_questions.md`).

For each wiki node, check that frontmatter contains exactly these 5 fields:
```yaml
type: note | entity | source-summary | reflection | insight | analysis | context | update
topic: {topic-name}
description: one-line summary
date_added: YYYY-MM-DD
tags: keyword1, keyword2, ...
```

Mark as **non-compliant** if:
- Any of the 5 required fields is missing
- Old fields are present: `confidence`, `confidence_last_updated`, `last_reviewed`,
  `last_reformatted`, `tags: [info|thought, human|ai]` (old binary tag format)
- `type` is not one of the valid values

Record each non-compliant node in a remediation list:
`{path} — reason: {missing field / old field present / invalid type}`

Also flag nodes with thin content (body under 100 words):
`{path} — thin content: may need expansion`

Do not fix anything in this step — only collect.

---

## Step 3 — Check .index.md completeness

For each `.index.md` found in Step 1:

**3a.** Read the `.index.md`.

**3b.** Count rows in the index table.
- If a folder has content pages not listed in the `.index.md`, add to action list:
  "Missing from index: {page path}"
- If the `.index.md` has a placeholder row (`| — |`) but real pages exist, add:
  "Placeholder not replaced in {folder}/.index.md"

**3c. Oversized index:** If row count exceeds 50, add:
"Consider splitting {folder}/ (currently {N} rows in .index.md)"

**3d. Verify each linked page exists:**
For each `[title](slug.md)` link in the `.index.md`, check that the target file exists.
If not found, add: "Broken index link in {index path}: target {page} not found"

---

## Step 4 — Check for orphan pages

An orphan is a content page not referenced in any `.index.md` in the wiki.

For each content page:
- Check if the page filename appears in any `.index.md` via grep.
- If the grep returns no results, the page is an orphan. Add:
  "Orphan page: {page path} — not listed in any .index.md"

---

## Step 5 — Check for broken wikilinks

Scan all content pages for wikilinks:
`grep "\[\[" {memory_root}/wiki/**/*.md`

For each `[[topic/slug]]` found, check if `{memory_root}/wiki/{topic}/{slug}.md` exists.
If not, collect the unresolved link.

Group unresolved links by target. If a target is linked from 3+ pages, add:
"Missing page: [[{target}]] linked from {N} pages but has no wiki page yet"

---

## Step 6 — Check for potential contradictions

**6a.** Find pages in the same section (projects/ or knowledge/) covering the same entity
or concept (similar names, or linked to each other). Read both pages.

**6b.** Compare key claims. If a direct factual contradiction is found, add:
"Potential contradiction: {page A} says '{claim A}', {page B} says '{claim B}' — verify"

Do not flag stylistic differences — only factual contradictions.

---

## Step 7 — Suggest new investigations

Based on what you've read during this lint pass, identify gaps worth filling:

- Topics with only 1–2 pages that seem like they should have more depth
- Entities mentioned in many pages but without their own page (from Step 5)
- Any recurring unanswered questions in the content pages

Record these as **research targets** for Step 8.5.

---

## Step 8 — Remediate non-compliant nodes

For each node in the remediation list from Step 2:

**8a.** Read the existing node.

**8b.** Fix frontmatter:
- Add any missing required fields (use reasonable defaults: `type: note`, `tags: `)
- Remove old fields: `confidence`, `confidence_last_updated`, `last_reviewed`,
  `last_reformatted`
- Fix old binary tags format → infer appropriate `type` from content and set `tags` as
  comma-separated keywords

**8c.** If the body structure needs reorganisation (e.g. old Summary+KeyPoints format),
restructure using markdown headings appropriate to the content type. Preserve every
factual claim — do not invent or remove content.

**8d.** Write the updated file using `edit` (or `write` if the rewrite is complete).

**8e. Check for split candidates:** If a node contains multiple clearly distinct ideas,
add to report: "Split candidate: {path} — contains {N} distinct ideas: {brief list}.
Use spawn_memory_add_subagent to re-file the content as separate pages."

---

## Step 8.5 — Web research to fill identified gaps

Execute if Step 7 produced: thin topics, orphan pages, or missing pages linked from 3+ places.

**8.5a. Select research targets:** Select up to 3. Prioritise: missing pages with most
inbound links → thin topics → orphans.

**8.5b. For each research target:**
1. Formulate 1–2 search queries.
2. Call `WebSearch`. Collect top 3–5 results.
3. For the 1–2 most promising results, call `WebFetch`.
4. If substantive content is found, call `spawn_memory_add_subagent` with the fetched
   content and the relevant topic/project context.

**8.5c.** Record: targets researched, new nodes created, nodes updated, no-result targets.

---

## Step 9 — Answer one open question

**9a.** Read `{memory_root}/wiki/open_questions.md`.

If the file does not contain a `## Resolved` section, append it now:
```markdown

## Resolved

| # | Question | Answer Summary | Wiki Page | Date Resolved |
|---|----------|----------------|-----------|---------------|
| — | — | — | — | — |
```
Update `> **Last updated:**` to today.

**9b. Select a question:** From the `## Pending` table, pick the oldest row that does NOT
have "Attempted:" in its Context cell. If all have been attempted, pick the one attempted
longest ago. Skip to Step 10 if Pending table is empty.

**9c. Research the question:**
- Phase 1 — Call `spawn_memory_query_subagent` with the question text. Read the handoff.
- Phase 2 — If wiki is insufficient, call `WebSearch` + `WebFetch` on 1–2 results.

**9d. Evaluate resolvability:**
- **RESOLVED:** A clear, specific answer exists.
- **UNRESOLVABLE:** Insufficient information; requires primary source or domain expert.

**9e. If RESOLVED:**
1. Call `spawn_memory_add_subagent` to file a wiki node with the answer.
2. In `open_questions.md`:
   - Remove the question's row from `## Pending`.
   - Append to `## Resolved`: `| {#} | {Question} | {one-sentence summary} | {wiki page path} | {today} |`
   - Replace `| — |` placeholder if still present.
   - Update `> **Last updated:**` to today.

**9f. If UNRESOLVABLE:**
- Do NOT move the question to Resolved.
- Append " | Attempted: {YYYY-MM-DD}" to the Context cell of the row.

---

## Step 10 — Append to log.md and report

**Append to log.md:**
```
[{date}] lint | Health check | {N} pages, {N} issues found
```

**Report to user:**

### Reformatted (done automatically)
List each node rewritten, with a one-line note on what changed.

### Critical (fix these)
- Broken index links (`.index.md` points to non-existent page)
- Placeholder rows still in `.index.md` files

### Recommended (improve these)
- Orphan pages
- Missing pages with 3+ inbound links
- Oversized `.index.md` files
- Contradictions found
- Split candidates

### Research & Questions
- Research targets addressed
- New nodes filed from research
- Open question: resolved / attempted (unresolvable) / skipped

### Suggestions
- New investigations worth pursuing
- Topics that seem thin

For each item, provide the exact file path and a one-line description of the issue.

---

## Edge Cases

- **Wiki not initialised:** If `{memory_root}/wiki/.index.md` does not exist, stop
  and tell the user to run `/init` first.
- **Empty wiki (no content pages yet):** Report "Wiki is empty — no pages to lint."
  Skip all checks and do not append to log.md.
- **grep returns too many results:** Limit to first 200 matches. Note truncation in report.
- **Very large wiki (200+ pages):** Prioritise: format remediation (Step 8) > broken links
  (Step 5) > orphans (Step 4) > missing pages (Step 5) > contradictions (Step 6).
  Report which checks were skipped.
- **WebSearch/WebFetch unavailable:** Skip Steps 8.5 and 9 web phase. Note in report.
- **open_questions.md missing:** Skip Step 9. Note in report.
- **All Pending questions already attempted:** Pick the one with the oldest "Attempted:" date.
