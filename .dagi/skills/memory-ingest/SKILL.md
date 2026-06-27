---
name: memory-ingest
description: Ingest raw source files from {memory_root}/raw/ — classify, delegate wiki-writing to memory-add, derive a descriptive archive name, then move originals to sources/
---

# memory-ingest — Ingest Raw Sources

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
| Search file contents | `Grep` with `path: {memory_root}/` |
| Find files by pattern | `Glob` with `path: {memory_root}/` |

Use **bash** only for operations the tools cannot do:

| Operation | Command |
|-----------|---------|
| List raw/ | `bash: dir "{memory_root}\raw"` (non-C: drives) |

Use the **`copy` tool** for all file archiving and moves (see Step 7).

---

## Purpose

Process files in `{memory_root}/raw/`: read and classify them, delegate wiki-writing to
`memory-add`, derive a descriptive archive name, then move the originals to `{memory_root}/sources/`.

`memory-ingest` owns the file I/O, archive naming, and archiving.
`memory-add` owns all wiki-writing (nodes, entity pages, index updates).

Run this skill whenever new files appear in `{memory_root}/raw/`.

---

## Step 0 — Resolve memory root

1. Attempt to read `{cwd}/config.yaml`.
2. If the file exists and contains a non-empty `memory_root:` key that is not
   commented out, use that value as `{memory_root}` for all subsequent steps.
   Strip any surrounding quotes and trailing slashes.
3. If the file does not exist, or `memory_root` is absent, commented out, or empty,
   fall back to `{cwd}/.dagi/memory` as `{memory_root}`.
4. Note the resolved path to the user only if it differs from the default
   (e.g. "Using memory root: G:\My Drive\dagi-memory").

---

## Step 1 — Discover files in `raw/`

Use `find` with pattern `*` and path `{memory_root}/raw/` to list all files.

If `raw/` is empty, report this and stop — nothing to ingest.

Collect the full list first. Process files **one at a time**. Complete all steps
for file N before starting file N+1.

---

## Step 2 — Check for duplicate ingestion

`read {memory_root}/wiki/log.md` and scan for the original filename.

If it appears in a prior `ingest` entry, warn the user and skip this file.

---

## Step 3 — Read the source file

`read {memory_root}/raw/{filename}`

If the file cannot be read (binary, corrupt), add to the final failure report.
Leave it in `raw/` and move to the next file.

For images (jpg, png, gif, webp), the `read` tool returns base64. Describe what
you see — this description becomes the content passed to `memory-add`.

---

## Step 4 — Determine topic hint

Based on the file content, determine:

1. **Topic** — primary subject area in kebab-case (1–3 words).
2. **Sub-topic** (optional) — only if the topic folder already has sub-folders and
   this source clearly fits one. Default to topic-level when in doubt.

This is a hint passed to `memory-add`, which may refine it. The archive path is
determined in Step 6 after `memory-add` completes.

---

## Step 5 — Invoke memory-add subagent

Call `spawn_memory_add_subagent` with a task string containing:

```
[Ingest mode — do not append to log.md, memory-ingest will do that]

Topic hint: {topic from Step 4}
Content: {file content read in Step 3}
```

The subagent will write the wiki node(s), update index files, and return a handoff report.
Read the handoff report to obtain the final topic and slug(s) — you will need them in Steps 6–8.

Do NOT call `spawn_memory_add_subagent` again for the same file.

---

## Step 6 — Derive archive filename

After `memory-add` completes, choose a descriptive archive name for the **source document as
a whole** — not for any individual wiki node it produced. A file split into multiple nodes
still gets exactly one archive filename.

1. From the file content read in Step 3, derive a descriptive kebab-case name that
   captures the document's identity (e.g. `attention-is-all-you-need`, `2026-q1-budget-review`,
   `notes-on-knowledge-graphs`). Use the document's own title or main subject — not the
   wiki slugs produced by memory-add.
2. Preserve the original file extension.
3. Use `Glob` to list `{memory_root}/sources/{topic}/` and check for any existing file
   with the chosen name. If a conflict exists, append `-2`, `-3`, etc. until a free name
   is found.
4. The final archive path is: `{memory_root}/sources/{topic}/{chosen-name}.{ext}`

---

## Step 7 — Archive the original file

Use the `copy` tool with `move=true` — this copies the file to the archive path then
removes the original in one atomic operation. Parent directories are created automatically.

```
copy(
  src="{memory_root}/raw/{original-filename}",
  dst="{memory_root}/sources/{topic}/{chosen-name}.{ext}",
  move=true
)
```

If `copy` returns an error, note the file for manual action in the final report and continue.
See Edge Cases for recovery guidance.

---

## Step 8 — Append to log.md

After the copy succeeds, `read {memory_root}/wiki/log.md`, then `edit` to append:

```markdown
[{YYYY-MM-DD}] ingest | {original-filename} | {memory_root}/wiki/{section}/{topic}/{slug}.md
```

Where `{section}` is `projects` or `knowledge`, per the memory-add handoff report.

---

## Step 9 — Repeat for next file

Return to Step 2 for the next file in the list from Step 1.
Continue until all files in `raw/` are processed.

---

## Step 10 — Final report

After all files are processed:

1. **Ingested:** original filename, topic, archive path, wiki node path(s)
2. **Pages created / updated:** from memory-add's reports
3. **Failures:** files that could not be read or processed, with reason
4. **Manual actions needed:** files requiring user intervention (see Edge Cases)

---

## Edge Cases

- **Wiki not initialised:** If `{memory_root}/wiki/.index.md` does not exist, stop
  and tell the user to run `/init` first.
- **Already-ingested file:** If original filename appears in `log.md`, warn and skip.
- **Partial failure (memory-add succeeded, log/copy failed):** The duplicate check in Step 2 scans only `log.md` — if `memory-add` completed but the subsequent log write or `copy` failed, there is no record in `log.md` and the next ingest run will **not** detect the prior partial run. Re-running ingest in this state will create duplicate wiki nodes. Do NOT re-run. Instead, manually verify whether wiki nodes already exist at `{memory_root}/wiki/{topic}/{slug}.md` before re-processing the file. `memory-lint` should cross-reference `log.md` against actual wiki state to surface orphaned nodes.
- **Unreadable file:** Leave in `raw/`. Report the failure. Do not proceed to Steps 5–8.
- **`copy` tool error after memory-add succeeds:** Wiki nodes already exist. Do NOT
  re-run ingest — it will create duplicate wiki nodes. Instead, manually copy the raw
  file to `{memory_root}/sources/{topic}/{chosen-name}.{ext}` and delete it from `raw/`.
- **memory-add reports a slug conflict:** The `-2` suffix is handled by memory-add.
  Record whatever slug(s) memory-add chose in the log entry.
