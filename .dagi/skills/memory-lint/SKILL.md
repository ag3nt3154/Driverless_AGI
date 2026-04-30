---
name: memory-lint
description: Health-check the dagi wiki — find orphans, contradictions, stale claims, oversized indexes, broken links, and non-compliant node formats. Remediates format issues, applies confidence decay, reviews oldest nodes, researches gaps, and answers one open question.
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
- Create directories: `bash: mkdir -p "{memory_root}/sources/{topic}"`
- List a directory on a non-C: drive: `bash: dir "{memory_root}\wiki\{topic}"`

---

## Purpose

Audit the wiki at `{memory_root}/wiki/` and produce a prioritised action list.
Run periodically (e.g. after every 5–10 ingests) to keep the wiki healthy as it grows.

This skill has four phases:
1. **Read phase (Steps 1–9):** Inspect all wiki pages and collect issues.
2. **Confidence phase (Steps 9.5–9.8):** Apply decay, update contradictions, review oldest nodes.
3. **Remediation phase (Step 10):** Rewrite non-compliant nodes and fill gaps via web research.
4. **Open question phase (Step 10.7):** Attempt to resolve one pending question.

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
- `index.md` files — folder navigation indexes
- `log.md`, `overview.md`, `open_questions.md` — meta files (root-level)
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

Record each contradiction pair for Step 9.5 (confidence updates).

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

Add these as suggestions (not action items) in the report. Also record them as
**research targets** for Step 10.5.

---

## Step 9.5 — Apply confidence decay

For every content page enumerated in Step 1 that has a `confidence:` field in
its frontmatter:

1. Call the `confidence_decay` tool with:
   - `old_score`: value from `confidence:` in frontmatter
   - `date_added`: value from `confidence_last_updated:` frontmatter field
     (use `date_added` if `confidence_last_updated` is absent)
   - `current_date`: today's date (YYYY-MM-DD)
   - `decay_rate`: 0.005 (default)

2. If the returned `decayed_score` differs from `old_score` by more than 0.001:
   - Use `edit` to update the `confidence:` field in frontmatter to `decayed_score`
     (rounded to 4 decimal places).
   - Update `confidence_last_updated:` to today's date.

3. If `decayed_score` is ≤ 0.3, add to Recommended action list:
   "Low-confidence: {path} ({decayed_score}) — scheduled for lint review."

4. Collect count of nodes updated and total score delta for the Step 11 log entry.

**Contradiction confidence updates:**
For each contradiction pair recorded in Step 7, apply the contradiction rule:
- Identify the node with the higher score (H) and the lower score (L).
- H_new = max(0.2, H - 0.5 * L)
- L_new = 0.2  (floor — do not zero out entirely)
- Update both nodes' `confidence` and `confidence_last_updated` via `edit`.
- Add to Recommended action list:
  "Contradiction confidence applied: {path A} → {H_new}, {path B} → 0.2
   — verify which claim is correct"

**Nodes missing `confidence:` field:**
Add to action list: "Missing confidence field: {path} — assign initial score based on tags"
Do NOT auto-assign scores — flag for user review.

---

## Step 9.8 — Periodic node review

Read the `lint_review_count` setting from `config.yaml` (default: 5 if absent).
This is the number of nodes to review in this lint run.

**9.8a.** From all content pages enumerated in Step 1, sort by `last_reviewed`
ascending (oldest first). If `last_reviewed` is absent from frontmatter, treat
the node's `date_added` as its `last_reviewed` date. Select the top N nodes
(where N = `lint_review_count`).

**9.8b. For each selected node:**

  1. Read the full node content.

  2. Review the node for the following (collect each as a distinct problem):
     - **Factual accuracy:** do key claims hold up against other wiki pages?
       `grep` for related entities/topics; if claims seem inconsistent, note it.
     - **Cross-wiki consistency:** does this contradict any other page not yet
       caught by Step 7? Check wikilinks and entity pages.
     - **Structural completeness:** does the node have the required sections for
       its tag type (from Step 2's compliance table)? Are non-trivial sections present?
     - **Broken or missing wikilinks:** do `[[target]]` links in this node resolve
       to existing pages? (Use `find` to check.)
     - **Staleness signals:** does the node reference time-sensitive claims (e.g.
       "currently", "as of 2024") that may no longer be accurate?

  3. Count the total distinct problems found: `problem_count`.

  4. Compute new confidence:
     - If `problem_count == 0`: `new_confidence = 0.5`
     - If `problem_count > 0`: `new_confidence = max(0.2, 0.5 - 0.1 * problem_count)`

  5. Update frontmatter via `edit`:
     ```yaml
     confidence: {new_confidence}
     confidence_last_updated: {today}
     last_reviewed: {today}
     ```

  6. If `problem_count > 0`, append a review notes section to the node body:
     ```markdown
     ## Review Notes ({YYYY-MM-DD})
     - {problem description 1}
     - {problem description 2}
     ```
     If a `## Review Notes` section already exists, append the new entry below the
     previous one (preserve history).

**9.8c.** Collect for Step 11 (log) and Step 12 (report):
- Total nodes reviewed: {N}
- Clean (0 problems): {count} — confidence set to 0.5
- With problems: {count} — confidence reduced per formula above

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

If the node does not already have `confidence`, `confidence_last_updated`, and
`last_reviewed` frontmatter fields, add them now with values based on the node's
existing tags (use the initial confidence table from memory-add Step 6) and today's
date.

**10e. Check for split candidates:** If the node contains multiple distinct ideas
that each warrant their own node (as defined in memory-add Step 5), do NOT split
automatically. Instead, add to the report:
"Split candidate: {path} — contains {N} distinct ideas: {brief list}. Run memory-add
 on this node's content to split it properly."

**10f. Write** the updated file using `edit` (or `write` if the rewrite is complete).
Update the frontmatter to add:
```yaml
last_reformatted: YYYY-MM-DD
```

Keep all other frontmatter fields unchanged.

**10g. Log each remediation** internally (collect path + action for Step 11).

---

## Step 10.5 — Web research to fill identified gaps

Execute this step if Step 9 or Steps 3–6 produced any of the following flags:
- A topic with only 1–2 pages (thin topic)
- An orphan page whose subject could benefit from additional context
- A missing page linked from 3+ places (from Step 6)
- Any "thin content" flags from Step 2

**10.5a. Select research targets:**
From the collected flags, select up to 3 items to research in this lint pass.
Prioritise: missing pages with the most inbound links first → thin topics → orphans.
Do not attempt more than 3 per run.

**10.5b. For each research target:**
  1. Formulate 1–2 search queries relevant to the gap.
  2. Call `WebSearch` with each query. Collect the top 3–5 results.
  3. For the 1–2 most promising results, call `WebFetch` to retrieve full content.
  4. Assess whether the fetched content substantively addresses the gap:
     - **YES (substantive):** Call `memory-add` in `ingest` mode, passing the
       fetched content. Tag as `info` + `ai` (confidence: 0.50).
     - **PARTIAL (some useful info, incomplete):** Use `edit` to append the new
       information to the existing thin or orphan node directly. Apply the support
       rule to update its confidence:
         new_confidence = min(1.0, existing_conf + 0.5 * 0.50)
       Update `confidence_last_updated` to today.
     - **NONE (no useful content found):** Note in report:
       "Research attempted for {target}: no usable content found."

**10.5c. Collect for Step 11 (log) and Step 12 (report):**
- Targets researched: {list}
- New nodes created via memory-add: {list or "none"}
- Existing nodes updated: {list or "none"}
- Targets with no useful result: {list or "none"}

---

## Step 10.7 — Answer one open question

**10.7a. Ensure Resolved table exists:**
`read {memory_root}/wiki/open_questions.md`

If the file does not contain a `## Resolved` section, append it now:
```markdown

## Resolved

| # | Question | Answer Summary | Wiki Page | Date Added | Date Resolved |
|---|----------|---------------|-----------|------------|---------------|
| — | — | — | — | — | — |
```
Update `> **Last updated:**` to today.

**10.7b. Select a question:**
From the `## Pending` table, identify all rows that do NOT have "Attempted:" in
their Context cell (those have already been tried). Select the row with the oldest
`Date Added`. If multiple questions share the same date, pick the lowest `#`.

If all Pending questions have been attempted, pick the one attempted longest ago.
If the Pending table is empty or has only placeholder rows, skip to Step 11.

**10.7c. Research the question:**

Phase 1 — Wiki traversal:
  Use memory-query logic (Steps 3–6 of memory-query) to search the wiki for
  information relevant to the question. Read any pages found.

Phase 2 — Web research (if wiki is insufficient):
  If the wiki does not contain enough to answer confidently, run `WebSearch` with
  the question text as the query. Fetch content from the 1–2 most relevant results
  via `WebFetch`.

**10.7d. Evaluate resolvability:**
- **RESOLVED:** The question can be answered with reasonable confidence from wiki
  and/or web sources. A clear, specific answer exists.
- **UNRESOLVABLE:** Insufficient information is available; the question likely
  requires a primary source, domain expert, or human verification.

**10.7e. If RESOLVED:**
  1. Call `memory-add` in `ingest` mode to file a new wiki node containing the
     answer. Tag as `info` + `ai` (confidence: 0.50) if web-sourced; `info` + `human`
     (confidence: 0.75) if the answer comes entirely from wiki synthesis.
  2. In `open_questions.md`:
     a. Remove the question's row from the `## Pending` table.
     b. Append to the `## Resolved` table:
        `| {#} | {Question} | {one-sentence answer summary} | [[{topic}/{slug}]] | {original date_added} | {today} |`
     c. Replace the `| — |` placeholder in Resolved if still present.
     d. Update `> **Last updated:**` to today.
  3. Record: "Open question #{N} resolved: '{question}' → filed at {path}"

**10.7f. If UNRESOLVABLE:**
  1. Do NOT move the question to Resolved.
  2. Use `edit` to append " | Attempted: {YYYY-MM-DD}" to the Context cell of the
     question's row in the Pending table.
  3. Record: "Open question #{N} attempted but unresolvable: '{question}'"

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
- Confidence decay applied: {N} nodes updated
- Contradiction confidence updates: {count}
- Missing confidence fields flagged: {count}
- Nodes reviewed: {N} ({comma-separated list of slugs})
- Review outcomes: {N} clean (→0.5), {N} with problems (scores: {list})
- Research phase: {N} targets, {N} new nodes, {N} existing nodes updated
- Open question resolved: {yes — #{N} "{question text}" → {path} / no — #{N} attempted / skipped}
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
- Low-confidence nodes (score ≤ 0.3 after decay)

### Confidence Health
- Nodes updated by decay: {list — slug: old_score → new_score, or "none"}
- Contradiction confidence applied: {list — slug A → H_new, slug B → 0.2, or "none"}
- Missing confidence field: {list or "none"}
- Nodes reviewed this run: {list — slug: old_score → new_score, "clean" or N problems}

### Research & Questions
- Research targets addressed: {list or "none"}
- New nodes filed from research: {list with paths, or "none"}
- Existing nodes updated from research: {list or "none"}
- Open question: {resolved → #{N} "{question}" → {path} / attempted → #{N} "{question}" (unresolvable) / skipped}

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
  (Step 5) > confidence decay (Step 9.5) > node review (Step 9.8) > orphans (Step 4)
  > missing pages (Step 6) > contradictions (Step 7). Report which checks were skipped.
- **WebSearch/WebFetch unavailable:** Skip Step 10.5 and Step 10.7 web phase. Note
  in report: "Web research unavailable — Steps 10.5/10.7 skipped."
- **open_questions.md missing:** Skip Step 10.7. Note in report.
- **All Pending questions already attempted:** In Step 10.7b, pick the one with the
  oldest "Attempted:" date and retry it.
- **config.yaml missing lint_review_count:** Default to 5 nodes per run.
