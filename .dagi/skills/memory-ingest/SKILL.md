---
name: memory-ingest
description: Ingest raw source files from .dagi/memory/raw/ — classify, archive originals to sources/, then delegate wiki-writing to memory-add
---

# memory-ingest — Ingest Raw Sources

## Purpose

Process files in `.dagi/memory/raw/`: read and classify them, archive the originals
to `.dagi/memory/sources/`, then call the `memory-add` skill to integrate each one
into the wiki.

`memory-ingest` owns the file I/O and archiving.
`memory-add` owns all wiki-writing (nodes, entity pages, index updates).

Run this skill whenever new files appear in `.dagi/memory/raw/`.

---

## Step 1 — Discover files in `raw/`

Use `find` with pattern `*` and path `.dagi/memory/raw/` to list all files.

If `raw/` is empty, report this and stop — nothing to ingest.

Collect the full list first. Process files **one at a time**. Complete all steps
for file N before starting file N+1.

---

## Step 2 — Check for duplicate ingestion

`read .dagi/memory/wiki/log.md` and scan for the filename.

If it appears in a prior `ingest` entry, warn the user and skip this file.

---

## Step 3 — Read the source file

`read .dagi/memory/raw/{filename}`

If the file cannot be read (binary, corrupt), add to the final failure report.
Leave it in `raw/` and move to the next file.

For images (jpg, png, gif, webp), the `read` tool returns base64. Describe what
you see — this description becomes the content passed to `memory-add`.

---

## Step 4 — Determine topic and archive path

Based on the file content, determine:

1. **Topic** — primary subject area in kebab-case (1–3 words).
2. **Sub-topic** (optional) — only if the topic folder already has sub-folders and
   this source clearly fits one. Default to topic-level when in doubt.

**Archive path:**
- Topic-level: `.dagi/memory/sources/{topic}/{filename}`
- Sub-topic: `.dagi/memory/sources/{topic}/{subtopic}/{filename}`

The `sources/` hierarchy mirrors `wiki/` — same topic/sub-topic names.

---

## Step 5 — Archive the original file

1. Content is already in hand from Step 3.
2. `write` it to the archive path from Step 4.
3. After confirming the write succeeded, delete the original:

```bash
rm ".dagi/memory/raw/{filename}"
```

If `bash` is unavailable, note the file for manual deletion in the final report
and continue.

---

## Step 6 — Invoke memory-add (ingest mode)

Load the `memory-add` skill:

```
skill("memory-add")
```

Then follow `memory-add` with these inputs:

- **Mode:** `ingest` (memory-ingest will write the log entry — memory-add must skip Step 8)
- **Content:** the file content read in Step 3
- **Archive path:** the path written in Step 5 (e.g. `.dagi/memory/sources/{topic}/{filename}`)
- **Topic hint:** the topic determined in Step 4 (memory-add may refine it)

Follow all steps of `memory-add` except Step 8 (log append) — that is handled here
in Step 7.

---

## Step 7 — Append to log.md

After `memory-add` completes, `read .dagi/memory/wiki/log.md`, then `edit` to append:

```markdown
## [YYYY-MM-DD] ingest | {filename}
- Topic: {topic}{/subtopic if applicable}
- Archived: .dagi/memory/raw/{filename} → .dagi/memory/sources/{topic}/{filename}
- Wiki node: .dagi/memory/wiki/{topic}/{slug}.md
- Pages created: {list from memory-add report, or "none"}
- Pages updated: {list from memory-add report, or "none"}
- index.md files updated: {list}
```

---

## Step 8 — Repeat for next file

Return to Step 2 for the next file in the list from Step 1.
Continue until all files in `raw/` are processed.

---

## Step 9 — Final report

After all files are processed:

1. **Ingested:** file name, topic, archive path, wiki node path
2. **Pages created / updated:** from memory-add's reports
3. **Failures:** files that could not be read or processed, with reason
4. **Manual deletions needed:** files the user must remove from `raw/` manually

---

## Edge Cases

- **Wiki not initialised:** If `.dagi/memory/wiki/index.md` does not exist, stop
  and tell the user to run `/memory-init` first.
- **Already-ingested file:** If filename appears in `log.md`, warn and skip.
- **Unreadable file:** Leave in `raw/`. Report the failure. Do not archive.
- **`bash` unavailable:** Skip the `rm` in Step 5; note for manual deletion.
- **memory-add reports a slug conflict:** The `-2` suffix is handled by memory-add.
  Record whatever slug memory-add chose in the log entry.
