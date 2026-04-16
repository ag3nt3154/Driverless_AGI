---
name: ingest-raw
description: Process files in raw/, classify them, move to wiki/sources/, and update all wiki documents
---

# ingest-raw — Ingest Raw Source Files

## Purpose

Read every file in `raw/`, understand its contents, move it to the correct
`wiki/sources/{type}/` subdirectory, and update the six wiki documents accordingly.
Run this skill each time new files are dropped into `raw/`.

---

## Step 1 — Discover files in `raw/`

Use `find` with pattern `*` and path `raw/` to list all files present.

If `raw/` is empty or no files are found, report this to the user and stop — there
is nothing to ingest.

Collect the full list before processing anything. Process files one at a time in
alphabetical order. Complete all steps for file N before starting file N+1.

---

## Step 2 — Read and classify each file

For each file:

**2a. Read the file** using `read raw/{filename}`.

**2b. Classify the source type** based on extension and content:

| Type | Assign when… |
|------|-------------|
| `emails` | Extension is `.eml` or `.msg`, OR content begins with email headers (`From:`, `To:`, `Subject:`, `Date:`) |
| `meetings` | Filename contains "meeting", "minutes", "standup", or "retro"; OR content shows attendee list + action items pattern |
| `docs` | Extension is `.pdf`, `.docx`, `.doc`, `.txt`, or `.md` — and does not match emails or meetings |
| `misc` | Anything that does not fit the above |

**2c. Determine the destination path:**
`wiki/sources/{type}/{original-filename}`

If a file with that name already exists at the destination, append `_2`, `_3`, etc.
before the extension. Example: `brief.md` → `brief_2.md`.

---

## Step 3 — Check for duplicate ingestion

Before processing, read `wiki/index.md` and scan for the source filename in the
Source File column. If found, warn the user that this file has already been ingested
and skip it. Do not re-process already-indexed files.

---

## Step 4 — Extract structured information

While reading the file, extract and note the following (record "not found" for any
that are absent):

- **Tasks and action items:** Any to-dos, deadlines, or delivery targets. Note the
  exact due date if present. If absent, record `TBD`.
- **Features:** Product features, system capabilities, or functional requirements.
  Note the feature name, brief description, and any date mentioned.
- **Key decisions:** Any explicitly stated or clearly implied decision. Include the
  rationale if given.
- **Stakeholder deliverables:** Tangible outputs requested by clients or stakeholders.
  Note recipient and due date if present.
- **Business or analysis inquiries:** Questions or investigations raised by stakeholders.
- **Missing or ambiguous information:** Deadlines not provided, requirements that need
  clarification, anything that cannot be resolved from the source alone.

Keep this working note in context — you will use it in Steps 6–11.

---

## Step 5 — Move the source file

1. The content was already read in Step 2. Now `write` it to
   `wiki/sources/{type}/{filename}`.
2. After confirming the write succeeded, delete the original:

```bash
rm raw/{filename}
```

If `bash` is unavailable, inform the user to manually delete `raw/{filename}` after
the session, and continue.

**Construct the hybrid link — reuse this in every wiki update below:**

- Obsidian wikilink: `[[sources/{type}/{filename}]]`
- Standard markdown link: `[{filename}](sources/{type}/{filename})`
- **Combined format (use this everywhere):**
  `[[sources/{type}/{filename}]] / [{filename}](sources/{type}/{filename})`

---

## Step 6 — Update `wiki/readme.md`

Read `wiki/readme.md` first.

For each extracted **feature:**
- Add a new row to the Features table:
  `| {Feature name} | {Brief description} | Planned | {YYYY-MM-DD today} | [[sources/{type}/{filename}]] |`
- If the table only has the placeholder row `| — | — | Planned | — | — |`, replace
  that row with the first real feature, then append subsequent ones.

If the source describes the overall **project use case** and the Use Case section
reads `_To be completed._`, replace that placeholder with a short paragraph
summarising what you extracted.

If the source describes **architecture**, do the same for the Architecture section.

If **key contacts** are mentioned (names, roles, emails), add or update rows in
the Key Contacts table.

Update the `> **Status:** Draft — last updated:` line to today's date.

**Edit strategy:** Always use `edit` for surgical changes. Re-read the file before
each `edit` call to confirm exact text. If a target string is not unique in the
file, append to the end of the relevant section instead.

---

## Step 7 — Update `wiki/schedule.md`

Read `wiki/schedule.md` first.

For each extracted **task or action item:**

If a due date was found:
```
- [ ] {Task description} — Due: {YYYY-MM-DD} | [[sources/{type}/{filename}]]
```

If no due date was found:
```
- [ ] {Task description} — Due: TBD | [[sources/{type}/{filename}]]
```
Additionally, note this task — you will add an open question for it in Step 9.

If the Active Tasks section currently reads `_No tasks recorded yet._`, replace that
line entirely with the first new task entry, then append subsequent ones below it.

For milestones, append a row to the Milestones table:
`| {Milestone} | {Date or TBD} | Pending | [[sources/{type}/{filename}]] |`

Update the `> **Last updated:**` date to today.

---

## Step 8 — Update `wiki/deliverables.md`

Read `wiki/deliverables.md` first.

For each extracted **stakeholder deliverable**, append to the Client Deliverables table:
`| {Deliverable} | {Recipient if known, else "—"} | {Due date if known, else "—"} | Pending | [[sources/{type}/{filename}]] |`

For each extracted **analysis or business inquiry**, append to the Analysis & Business
Inquiries table:
`| {Inquiry description} | {Raised by if known, else "—"} | {Today's date} | Open | [[sources/{type}/{filename}]] |`

If a table only has the placeholder `| — |` row, replace that row with the first
real entry.

Update the `> **Last updated:**` date to today.

---

## Step 9 — Update `wiki/decisions.md`

Read `wiki/decisions.md` first.

For each extracted **decision:**
1. Count the current number of real rows (exclude the header row and any `| 1 | — |`
   placeholder row). Assign the next sequential number.
2. Append a row:
   `| {N} | {Decision statement} | {Rationale if available, else "—"} | {Date or today} | {Owner if known, else "—"} | [[sources/{type}/{filename}]] |`
3. If the table only has the placeholder row `| 1 | — | — | — | — | — |`, replace
   it with the first real decision.

Update the `> **Last updated:**` date to today.

---

## Step 10 — Update `wiki/open_questions.md`

Read `wiki/open_questions.md` first.

Add an entry for **each** of the following:
- Any task added to `schedule.md` with `Due: TBD` — question: "What is the deadline for: {task description}?"
- Any ambiguous, incomplete, or unresolvable item found in the source.
- Any requirement or deliverable where the recipient or scope is unclear.

For each question:
1. Count existing Pending rows (exclude header and placeholder). Assign next number.
2. Append to the Pending table:
   `| {N} | {Question} | {One-sentence context} | {Today's date} | [[sources/{type}/{filename}]] |`
3. If the table only has the placeholder row, replace it.

Update the `> **Last updated:**` date to today.

---

## Step 11 — Update `wiki/index.md`

Read `wiki/index.md` first.

Append one row for the file just processed. In "Wiki Documents Updated", list only
the documents that were actually modified (had rows added or text changed):

`| [[sources/{type}/{filename}]] / [{filename}](sources/{type}/{filename}) | {type} | {Today's date} | readme.md, schedule.md, decisions.md | {Notable notes or "—"} |`

If the table only has the placeholder `| — |` row, replace it.

Update the `> **Last updated:**` date to today.

---

## Step 12 — Repeat for next file

Return to Step 2 and process the next file from the list collected in Step 1.
Continue until all files in `raw/` have been processed.

---

## Step 13 — Final report

After all files are processed, report to the user:

1. **Ingested files:** List each file, its classified type, and destination path.
2. **Wiki updates:** For each wiki document, summarise what was added.
3. **Open questions raised:** List all questions added to `open_questions.md`.
4. **Failures:** Any files that could not be read or processed, with the reason.
5. **Manual actions needed:** Any files in `raw/` that the user must delete manually
   (if `bash rm` was unavailable).

---

## Edge Cases

- **Unreadable file (binary, corrupt):** Log it in the final report. Do not move it
  to `wiki/sources/`. Leave it in `raw/` and notify the user.
- **Ambiguous source type:** Default to `misc`. Note the uncertainty in the index
  row's Notes column.
- **Duplicate filename at destination:** Append `_2`, `_3`, etc. before the extension.
  Update all links to use the renamed filename.
- **Already-ingested file:** If the filename appears in `wiki/index.md`, warn the user
  and skip it entirely.
- **`edit` oldText not unique:** Use a larger surrounding context to make it unique.
  If still not possible, append to the end of the section. Use `write` for a full
  rewrite only as a last resort, after re-reading the current file content first.
- **Missing deadline:** Always add `Due: TBD` to schedule.md AND a question to
  open_questions.md. Never omit either entry.
- **Empty source file:** Move to `wiki/sources/misc/`. Add index row with
  "No content extracted" in Notes. Do not update other wiki documents.
- **Wiki not initialised:** If `wiki/readme.md` does not exist, stop and tell the user
  to run the `init-pms` skill first.
