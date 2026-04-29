---
name: memory-lint
description: Health-check the dagi wiki — find orphans, contradictions, stale claims, oversized indexes, broken links, and non-compliant node formats. Remediates format issues automatically.
---

# memory-lint — Wiki Health Check & Remediation

## Path Roots

All paths in this skill are under **memory root** (`{memory_root}`), NOT under CWD (`{cwd}`).
Use bash with absolute paths for all file I/O — `read`/`write`/`edit`/`find` resolve from CWD and will fail.
Use `dir` not `ls` on non-C: drives.

---

## Purpose

Audit the wiki at `{memory_root}/wiki/` and produce a prioritised action list.
Run periodically (e.g. after every 5–10 ingests) to keep the wiki healthy as it grows.

This skill has two phases:
1. **Read phase (Steps 1–9):** Inspect all wiki pages and collect issues.
2. **Remediation phase (Step 10):** Automatically rewrite non-compliant wiki nodes
   into the correct format. All other issues are reported for the user to act on.

---

## Step 1 — Enumerate all wiki pages

Use `find {memory_root}/wiki/ **/*.md` to collect every markdown file.

Categorise by type:
- `index.md` files — folder navigation indexes
- `log.md`, `overview.md` — meta files (root-level)
- All other `.md` files — content pages (wiki nodes, entity pages, concept pages)

Record the full list. You will use it in every subsequent check.

---

## Step 2 — Check node format compliance

Read every content page (skip `index.md`, `log.md`, `overview.md`, `open_questions.md`,
and `entity`-type pages — those have their own structure).

For each wiki node, classify it as **compliant** or **non-compliant**:

**Non-compliant** if the body uses the old format:
- Has a `## Summary` section AND/OR a `## Key Points` section as primary content
- Does NOT have sections appropriate to its tag type (see below)

**Compliant** if the body matches the tag type:

| Tag | Required sections (at least 3 of these must be present) |
|-----|----------------------------------------------------------|
| `info` | Background, Core Concepts, How It Works, Evidence & Examples, Implications & Applications, Limitations & Caveats |
| `thought` | Context & Premise, The Argument, Supporting Evidence, Conclusions, Open Questions |
| Missing tag | Flag as non-compliant regardless of sections |

Record each non-compliant node in a remediation list:
`{path} — reason: {old Summary+KeyPoints / missing type sections / missing tag}`

If a compliant node has thin sections (each section is 1 sentence or less and the
total body is under 150 words), add a separate flag:
`{path} — thin content: may need expansion from source`

Do not fix anything in this step — only collect.

---

## Step 3 — Check index.md completeness

For each `index.md` found in Step 1:

**3a. Read the index.md.**

**3b. Count rows** in "Pages in this folder" and "Sub-topics" tables.
- If a folder has content pages but they are not listed in its index.md, add them
  to the action list: "Missing from index: {page path}"
- If the index.md has a placeholder row (`| — |`) but pages exist, add to action
  list: "index.md placeholder not replaced in {folder}"

**3c. Oversized index.md:** If row count exceeds 50, add to action list:
"Consider splitting {folder}/ into sub-topics (currently {N} rows in index.md)"

**3d. Verify each linked page exists:**
For each `[[page]]` or `[page](path)` link in the index.md, check that the target
file exists using `find`. If not found, add to action list:
"Broken index link in {index path}: target {page} not found"

---

## Step 4 — Check for orphan pages

An orphan is a content page that has no inbound wikilinks from any other wiki page.

For each content page path:
`grep "{page slug}" {memory_root}/wiki/**/*.md`

If the grep returns no results (the page slug appears nowhere else in the wiki),
the page is an orphan. Add to action list:
"Orphan page: {page path} — not linked from any other wiki page"

Note: `overview.md` is expected to be an orphan initially. Only flag it after 5+
pages have been ingested.

---

## Step 5 — Check for broken source links

For each content page, check its `source:` frontmatter field and any inline links
pointing to `{memory_root}/sources/`:

`grep "sources/" {memory_root}/wiki/**/*.md`

For each source path referenced, verify the file exists:
`find {memory_root}/sources/ {filename}`

If not found, add to action list:
"Broken source link in {page path}: {source path} not found in archive"

---

## Step 6 — Check for missing entity/concept pages

Scan all content pages for wikilinks that point to pages that don't exist yet:
`grep "\[\[" {memory_root}/wiki/**/*.md`

For each `[[target]]` found, check if `{memory_root}/wiki/{topic}/{target}.md` exists.
If not, collect the unresolved link.

Group unresolved links by target name. If a target is linked from 3+ pages, add to
action list:
"Missing page: [[{target}]] linked from {N} pages but has no wiki page yet"

(Lower-frequency unresolved links are normal — only flag those with 3+ references.)

---

## Step 7 — Check for potential contradictions

This is a heuristic check — read the pages most likely to conflict.

**7a.** Find pages in the same topic folder that cover the same entity or concept
(similar names, or linked to each other). Read both pages.

**7b.** Compare key claims. If you find a direct contradiction (e.g. one page says
"X was published in 1945" and another says "X was published in 1948"), add to action
list:
"Potential contradiction: {page A} says '{claim A}', {page B} says '{claim B}' — verify"

Do not flag minor stylistic differences — only factual contradictions.

---

## Step 8 — Check overview.md currency

`read {memory_root}/wiki/overview.md`

If the overview still reads `_No sources ingested yet._` but log.md shows multiple
ingests, add to action list:
"overview.md has not been updated despite {N} ingests — consider running memory-ingest
 with a synthesis-focused source, or manually update overview.md"

If the overview's `Last updated` date is more than 30 days older than the most recent
log entry, add to action list:
"overview.md last updated {date} — may be stale relative to recent ingests"

---

## Step 9 — Suggest new investigations

Based on what you've read during this lint pass, identify gaps worth filling:

- Topics with only 1–2 pages that seem like they should have more depth
- Entities mentioned in many pages but without their own page (from Step 6)
- Topics where pages link outward to other topics heavily — the connection might
  warrant a synthesis page
- Any recurring questions in the source nodes that remain unanswered

Add these as suggestions (not action items) in the report.

---

## Step 10 — Remediate non-compliant nodes

For each node in the remediation list from Step 2, rewrite it into the correct format.

**Do not invent content.** Reorganise and expand what is already there. If a section
has no supporting material in the existing node, omit it rather than padding.

**10a. Read the existing node.**

**10b. Determine the target template** from the frontmatter `tags` field:
- Contains `info` → use the `info` template
- Contains `thought` → use the `thought` template
- Tag missing → default to `info` template, add `info` and `human` to frontmatter tags

**10c. Map existing content to new sections:**

| Old section | Maps to (info) | Maps to (thought) |
|-------------|---------------|-------------------|
| `## Summary` paragraphs | Background + How It Works (split by content) | Context & Premise + The Argument |
| `## Key Points` bullets | Evidence & Examples + Implications (split by content) | Supporting Evidence + Conclusions |
| Any inline definitions | Core Concepts | — |
| Caveats or "however" clauses | Limitations & Caveats | Open Questions |

Use judgment when splitting Summary content across sections — Background gets
context/motivation, How It Works gets mechanism/process. Don't arbitrarily chop;
keep logically coherent chunks together.

**10d. Rewrite the node** using the appropriate template structure. Preserve every
factual claim and specific detail from the original. Expand bullet points from Key
Points into prose where they are thin (1 sentence → 2–3 sentences of explanation).

**10e. Check for split candidates:** If the node contains multiple distinct ideas
that each warrant their own node (as defined in memory-add Step 4.5), do NOT split
automatically. Instead, add to the report:
"Split candidate: {path} — contains {N} distinct ideas: {brief list}. Run memory-add
 on this node's content to split it properly."

**10f. Write** the updated file using `edit` (or `write` if the rewrite is complete).
Update the frontmatter `date_added` to add a new field:
```yaml
last_reformatted: YYYY-MM-DD
```

Keep all other frontmatter fields unchanged.

**10g. Log each remediation** internally (collect path + action for Step 11).

---

## Step 11 — Append to log.md

`read {memory_root}/wiki/log.md` first, then append using `edit`:

```markdown
## [YYYY-MM-DD] lint | Health check
- Pages checked: {N}
- Non-compliant nodes found: {count}
- Nodes reformatted: {count}
- Split candidates flagged: {count}
- Orphans: {count}
- Broken links: {count}
- Contradictions: {count}
- Oversized indexes: {count}
- Other action items: {count}
```

---

## Step 12 — Report to user

Structure the report as:

### Reformatted (done automatically)
- List each node that was rewritten, with a one-line note on what changed
  (e.g. "Converted Summary+KeyPoints → Background/How It Works/Evidence/Implications")

### Critical (fix these)
- Broken source links (source file missing from archive)
- Broken index links (index.md points to non-existent page)
- Placeholder rows still in index.md files

### Recommended (improve these)
- Orphan pages
- Missing pages with 3+ inbound links
- Oversized index.md files (candidate for sub-topic split)
- Contradictions found
- Split candidates (nodes containing multiple distinct ideas)
- Thin nodes (compliant structure but very sparse content)

### Suggestions (optional improvements)
- Stale overview.md
- New investigations worth pursuing
- Topics that seem thin and could benefit from more sources

For each item, provide the exact file path and a one-line description of the issue.

---

## Edge Cases

- **Wiki not initialised:** If `{memory_root}/wiki/index.md` does not exist, stop
  and tell the user to run `/init` first.
- **Empty wiki (no content pages yet):** Report "Wiki is empty — no pages to lint."
  Skip all checks and do not append to log.md.
- **grep returns too many results:** Limit to first 200 matches. Note truncation in
  the report.
- **Node has neither Summary nor new sections:** Treat as non-compliant. Wrap all
  body content into the most fitting section based on content type.
- **Ambiguous tag (both `info` and `thought` absent):** Default to `info` template.
  Add `info` and `human` tags to frontmatter.
- **Very large wiki (200+ pages):** This lint pass may require many reads. If context
  window pressure is high, prioritise: format remediation (Step 10) > broken links
  (Step 5) > orphans (Step 4) > missing pages (Step 6) > contradictions (Step 7).
  Report which checks were skipped.
