---
name: memory-lint
description: Health-check the dagi wiki — find orphans, contradictions, stale claims, oversized indexes, and broken links
---

# memory-lint — Wiki Health Check

## Purpose

Audit the wiki at `.dagi/memory/wiki/` and produce a prioritised action list.
Run periodically (e.g. after every 5–10 ingests) to keep the wiki healthy as it grows.

This skill is read-only — it reports issues but does not fix them. The user decides
which actions to take.

---

## Step 1 — Enumerate all wiki pages

Use `find .dagi/memory/wiki/ **/*.md` to collect every markdown file.

Categorise by type:
- `index.md` files — folder navigation indexes
- `log.md`, `overview.md` — meta files (root-level)
- All other `.md` files — content pages (wiki nodes, entity pages, concept pages)

Record the full list. You will use it in every subsequent check.

---

## Step 2 — Check index.md completeness

For each `index.md` found in Step 1:

**2a. Read the index.md.**

**2b. Count rows** in "Pages in this folder" and "Sub-topics" tables.
- If a folder has content pages but they are not listed in its index.md, add them
  to the action list: "Missing from index: {page path}"
- If the index.md has a placeholder row (`| — |`) but pages exist, add to action
  list: "index.md placeholder not replaced in {folder}"

**2c. Oversized index.md:** If row count exceeds 50, add to action list:
"Consider splitting {folder}/ into sub-topics (currently {N} rows in index.md)"

**2d. Verify each linked page exists:**
For each `[[page]]` or `[page](path)` link in the index.md, check that the target
file exists using `find`. If not found, add to action list:
"Broken index link in {index path}: target {page} not found"

---

## Step 3 — Check for orphan pages

An orphan is a content page that has no inbound wikilinks from any other wiki page.

For each content page path:
`grep "{page slug}" .dagi/memory/wiki/**/*.md`

If the grep returns no results (the page slug appears nowhere else in the wiki),
the page is an orphan. Add to action list:
"Orphan page: {page path} — not linked from any other wiki page"

Note: `overview.md` is expected to be an orphan initially. Only flag it after 5+
pages have been ingested.

---

## Step 4 — Check for broken source links

For each content page, check its `source:` frontmatter field and any inline links
pointing to `.dagi/memory/sources/`:

`grep "sources/" .dagi/memory/wiki/**/*.md`

For each source path referenced, verify the file exists:
`find .dagi/memory/sources/ {filename}`

If not found, add to action list:
"Broken source link in {page path}: {source path} not found in archive"

---

## Step 5 — Check for missing entity/concept pages

Scan all content pages for wikilinks that point to pages that don't exist yet:
`grep "\[\[" .dagi/memory/wiki/**/*.md`

For each `[[target]]` found, check if `.dagi/memory/wiki/{topic}/{target}.md` exists.
If not, collect the unresolved link.

Group unresolved links by target name. If a target is linked from 3+ pages, add to
action list:
"Missing page: [[{target}]] linked from {N} pages but has no wiki page yet"

(Lower-frequency unresolved links are normal — only flag those with 3+ references.)

---

## Step 6 — Check for potential contradictions

This is a heuristic check — read the pages most likely to conflict.

**6a.** Find pages in the same topic folder that cover the same entity or concept
(similar names, or linked to each other). Read both pages.

**6b.** Compare key claims. If you find a direct contradiction (e.g. one page says
"X was published in 1945" and another says "X was published in 1948"), add to action
list:
"Potential contradiction: {page A} says '{claim A}', {page B} says '{claim B}' — verify"

Do not flag minor stylistic differences — only factual contradictions.

---

## Step 7 — Check overview.md currency

`read .dagi/memory/wiki/overview.md`

If the overview still reads `_No sources ingested yet._` but log.md shows multiple
ingests, add to action list:
"overview.md has not been updated despite {N} ingests — consider running memory-ingest
 with a synthesis-focused source, or manually update overview.md"

If the overview's `Last updated` date is more than 30 days older than the most recent
log entry, add to action list:
"overview.md last updated {date} — may be stale relative to recent ingests"

---

## Step 8 — Suggest new investigations

Based on what you've read during this lint pass, identify gaps worth filling:

- Topics with only 1–2 pages that seem like they should have more depth
- Entities mentioned in many pages but without their own page (from Step 5)
- Topics where pages link outward to other topics heavily — the connection might
  warrant a synthesis page
- Any recurring questions in the source nodes that remain unanswered

Add these as suggestions (not action items) in the report.

---

## Step 9 — Append to log.md

`read .dagi/memory/wiki/log.md` first, then append using `edit`:

```markdown
## [YYYY-MM-DD] lint | Health check
- Pages checked: {N}
- Orphans: {count}
- Broken links: {count}
- Contradictions: {count}
- Oversized indexes: {count}
- Action items: {total count}
```

---

## Step 10 — Report to user

Structure the report as:

### Critical (fix these)
- Broken source links (source file missing from archive)
- Broken index links (index.md points to non-existent page)
- Placeholder rows still in index.md files

### Recommended (improve these)
- Orphan pages
- Missing pages with 3+ inbound links
- Oversized index.md files (candidate for sub-topic split)
- Contradictions found

### Suggestions (optional improvements)
- Stale overview.md
- New investigations worth pursuing
- Topics that seem thin and could benefit from more sources

For each item, provide the exact file path and a one-line description of the issue.

---

## Edge Cases

- **Wiki not initialised:** If `.dagi/memory/wiki/index.md` does not exist, stop
  and tell the user to run `/init` first.
- **Empty wiki (no content pages yet):** Report "Wiki is empty — no pages to lint."
  Skip all checks and do not append to log.md.
- **grep returns too many results:** Limit to first 200 matches. Note truncation in
  the report.
- **Very large wiki (200+ pages):** This lint pass may require many reads. If context
  window pressure is high, prioritise: broken links (Step 4) > orphans (Step 3) >
  missing pages (Step 5) > contradictions (Step 6). Report which checks were skipped.
