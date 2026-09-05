---
name: review-session
description: Deep-read DAGI session logs described in free text (a folder, explicit files, a time window, "last N", etc.), analyse tasks/actions/errors/corrections across all of them, and accumulate findings into one running markdown report. Cross-session shortcomings and improvement items are synthesised once at the end.
triggers: review session, review these sessions, review sessions in, session review, analyse session, analyze session, review the session, review last session, review recent sessions, review sessions from last hour, review today's sessions
---

# review-session — Cross-Session Deep Review

## Purpose

Read one or more DAGI session log(s) in full, understand what happened in each, and
accumulate findings into a **single running report** so that patterns which recur across
sessions become visible as one insight instead of being written up separately per session.

**Output:** one file per invocation —
`{DAGI_ROOT}/.dagi/self-review/review_{run-datetime}.md`

**Determine DAGI_ROOT** from this file's own path:
this file is at `{DAGI_ROOT}/.dagi/skills/review-session/SKILL.md`,
so DAGI_ROOT is three levels up.

The helper scripts live alongside this file:
`{DAGI_ROOT}/.dagi/skills/review-session/parse_jsonl_logs.py`
`{DAGI_ROOT}/.dagi/skills/review-session/chunk_session.py`

`run-datetime` is fixed once, at the start of the invocation (format `YYYY-MM-DD_HH-MM-SS`),
and used for both the report filename and the plan filename. It is **not** a session ID.

This skill does not write to `TODO.md`. It only produces the review report — turning
findings into work-queue items is a separate, manual decision.

---

## Step 1 — Resolve the session list from free text

There is no fixed parameter grammar. The user describes what to review in plain language;
interpret it using judgment plus the discovery tools below. Do not force the user into a
specific syntax.

**Discovery tools:**
- `find` — for an explicit folder, explicit file list, or glob the user names directly
  (e.g. "review the sessions in G:\logs\batch3", "review session_2026-07-01_09-00-00.jsonl
  and session_2026-07-01_10-15-00.jsonl")
- `conda run -n dagi python {SKILL_DIR}/chunk_session.py --list {logs_dir}` — for anything
  implying recency, a date, or "the usual logs directory" (`{DAGI_ROOT}/.dagi/logs` unless
  the user names another folder). Returns metadata (`path`, `started_at`, `model`,
  `node_count`) sorted newest-first — filter and reorder as needed.
- `datetime_now()` (if available) — to resolve relative time phrases ("today", "since
  yesterday 3pm", "last 2 hours"). If unavailable, fall back to the most recent session's
  `started_at` as a proxy for "now" and note the limitation.

**Worked examples:**

| User says | Resolution |
|---|---|
| "review sessions in G:\some\folder" | `find` that folder for `*.jsonl`, sort by filename ascending |
| "review session_A.jsonl and session_B.jsonl" | Use exactly those two paths, in the order given (or chronological if order isn't meaningful) |
| "review the last 3 sessions" | `chunk_session.py --list`, take the first 3 (newest-first), then reverse to chronological order |
| "review today's sessions" | `datetime_now()` → local midnight cutoff → `chunk_session.py --list`, keep entries with `started_at >= cutoff` |
| "review sessions since yesterday 3pm" | Same pattern, cutoff = yesterday 15:00 local |
| no description given | See **default** below |

**Default (no description given):**
Look for the most recent `review_*.md` file already in `{DAGI_ROOT}/.dagi/self-review/`.
Parse its `run-datetime` from the filename and treat it as a cursor: review sessions with
`started_at` after that cursor. If no prior report file exists, default to the 5 most recent
sessions in `{DAGI_ROOT}/.dagi/logs`.

**Ordering:** chronological oldest → newest by default, so the report reads as a narrative
over time. Only reverse this if the user's phrasing explicitly implies newest-first.

**Empty result:** if the resolved list is empty, report why and stop — do not create a
report file:
> "No sessions found matching '{description}'. {brief reason}."

---

## Step 2 — Initialize the report file

Create `{DAGI_ROOT}/.dagi/self-review/review_{run-datetime}.md` (create the
`.dagi/self-review/` directory first if it doesn't exist) with this skeleton:

```markdown
# Session Review — {run-datetime}

## Run Info
- Sessions requested: "{verbatim user description, or "(default — since last review)"}"
- Interpreted as: {N} session file(s) — {one-line resolution explanation}
- Sessions reviewed: (pending)
- Sessions skipped: (pending)

## Sessions Reviewed
| Session ID | Model | Started | Tokens (in/out) | Tool calls | Errors | Corrections |
|---|---|---|---|---|---|---|

## Sessions Skipped

## Tasks

## Agent Actions

## Errors & Problems

## User Corrections

## User Feedback
```

The "Sessions reviewed"/"Sessions skipped" counts and the closing sections
(`## Cross-Session Analysis`, `## Suggested Improvements`, `## Plan File`) are filled in
later — see Steps 4 and 5.

---

## Step 3 — Process each session in order

For every session path in the resolved list, do all of the following before moving to the
next session.

### 3a — Meaningfulness check

Read only the first 10 records of the raw JSONL file (use the `read` tool with a line
limit).

**Skip the session** (go to 3f below, do not analyse further) if ALL of the following are
true:
- `node_count` < 5, OR
- The only user message is a single word or test phrase ("test", "hello", "hi", "ok"), OR
- There are no tool calls and no assistant content (empty exchange)

**Always analyse** sessions that have errors, user corrections, or meaningful tool activity
— even if short, those are the most valuable to review.

### 3b — Simplify and decide reading strategy

Get metadata for the report table:
```
conda run -n dagi python {SKILL_DIR}/chunk_session.py <path> --info
```

Run the simplifier in stats-only mode to decide the reading strategy:
```
conda run -n dagi python {SKILL_DIR}/parse_jsonl_logs.py <path> --stats
```

- If `fits_in_context` is **true** → generate the simplified log
  (`parse_jsonl_logs.py <path> --output /tmp/dagi_simplified.jsonl`) and read it directly
  in one pass.
- If `fits_in_context` is **false** → generate the simplified log the same way, then chunk
  it: `conda run -n dagi python {SKILL_DIR}/chunk_session.py /tmp/dagi_simplified.jsonl`
  (default `--chunk-size 60 --overlap 10`). Process chunks in order; for chunks with
  `is_overlap_start: true`, read the leading `overlap_node_count` records for context only
  — do not re-extract findings from them, they were already processed in the previous chunk.

### 3c — Extract findings

Apply these criteria to the records read in 3b (all of them for single-pass, only the new
records per chunk for windowed reading):

**Tasks** — `"type": "message"`, `"entity": "user"` records. The first user message is
usually the primary task; later user messages may introduce sub-tasks. Record each as a
short one-sentence description.

**Agent actions** — `"type": "tool_call"` records (tool name + brief summary of what was
invoked), significant decisions/explanations in assistant `content`, and
`subagent_start`/`subagent_end` records (note type + task).

**Errors & problems** — `"type": "tool_call"` records with `"error": true`; the same tool
name with near-identical input appearing 3+ times in a row (retry loop); assistant messages
stating something can't be done.

**User corrections** — mid-session (not first) user messages containing "no", "wrong",
"not right", "not what I", "redo", "try again", "start over", "actually", "wait",
"instead", or a rephrased repeat of an earlier instruction. Quote the relevant portion
verbatim.

**User feedback** — explicit positive ("good", "perfect", "great", "exactly", "yes that's
right") or negative ("stop doing X", "don't do that", "I don't want you to") signals.

### 3d — Dedup against the running report

Read the report file's current content (it's cheap — only extracted bullets, not raw logs).
For each new finding, compare it against existing bullets in the matching section for
semantic equivalence (same error type + tool, same root cause, same correction theme, same
task already recorded, etc.):

- **Match found** → append this session's ID to that bullet's tag list, e.g.
  `[2026-06-30_10-15-00, 2026-07-01_09-02-11]`. Do not duplicate the line.
- **No match** → add a new bullet tagged with just this session's ID:
  `[{session-id}] {finding text}`.

### 3e — Apply the update

Use **one `edit` call** to apply everything for this session at once: the new/updated
bullets across all finding sections, plus the new row in the "Sessions Reviewed" table
(session ID, model, started, tokens in/out, tool call count, error count, correction count
— all from the 3b metadata + 3c extraction). Do not make multiple partial edits per session.

Then continue to the next session in the list (back to 3a).

### 3f — Skipped sessions

If 3a determined the session should be skipped, use a small `edit` call to append one line
to "Sessions Skipped":
```
- {session-id} — {reason, e.g. "trivially short (3 nodes, no task)"}
```
Then continue to the next session.

---

## Step 4 — Update run totals

Once every session in the list has been processed (analysed or skipped), edit the
"Run Info" section to fill in the final counts:
```
- Sessions reviewed: {N}
- Sessions skipped: {N}
```

If **every** session was skipped, note this plainly in Run Info
("No meaningful sessions found among the candidates.") and skip Step 5 (synthesis) entirely
— there is nothing to synthesise. The report file still stands as the record of what was
skipped and why.

---

## Step 5 — Cross-session synthesis (once, at the end)

Skip this step entirely if no sessions were analysed (see Step 4).

### 5a — Create plan

```
create_plan(task_summary="cross-session-analysis")
```

### 5b — Draft the analysis

Read the full running report (all sections are now populated with tagged findings). Write a
plan file at `{DAGI_ROOT}/.dagi/self-review/plan_{run-datetime}.md` with:

**Shortcomings** — concrete problems observed across the reviewed sessions:
1. **Task completion**: were tasks completed? If not, in how many sessions, and why?
2. **Error handling**: were errors recovered from gracefully, or retried blindly? How often
   does the same error recur (use the tag counts from Step 3d as evidence)?
3. **Efficiency**: redundant steps, repeated file reads, excessive tool calls — recurring
   across sessions or isolated?
4. **Understanding**: did corrections indicate misunderstanding? How many sessions needed
   corrections, and of what kind?
5. **Token efficiency**: aggregate `total_input_tokens` across sessions; flag task types that
   are disproportionately expensive.

**Areas of improvement** — higher-level patterns behind the shortcomings. Use the
session-tag counts on each finding to distinguish genuinely recurring issues (strong signal,
multiple session tags) from one-off noise (single session tag). Generalize: if the same root
cause produced findings tagged across several sessions, that is one area of improvement, not
several.

**Improvement items** — concrete, actionable:
- Format: `[priority: high/medium/low] {verb phrase} — {one-sentence rationale} — evidence: sessions {ids}`
- Prefer items that address a root cause behind multiple tagged findings over items that
  address a single session's one-off issue.
- Each item should specify what to change, where (file/tool/prompt), and why.
- Determine whether each item needs an architectural change or a simple edit/addition.

### 5c — Set active plan

```
set_active_plan(path="{plan_file_path}")
```

### 5d — Append synthesis to the report

Use **one `edit` call** to append these sections to
`{DAGI_ROOT}/.dagi/self-review/review_{run-datetime}.md`:

```markdown
## Cross-Session Analysis

### Shortcomings
{copied from the plan file, Step 5b}

### Areas of Improvement
{copied from the plan file, Step 5b}

## Suggested Improvements
1. [priority] {improvement item} — evidence: sessions {ids}
2. [priority] {improvement item} — evidence: sessions {ids}

## Plan File
{DAGI_ROOT}/.dagi/self-review/plan_{run-datetime}.md
```

The plan file is retained as a permanent artifact alongside the report.

---

## Edge Cases

| Situation | Handling |
|---|---|
| No sessions resolved from the description | Report why, stop — do not create a report file |
| All resolved sessions are trivial | Write the report header + Sessions Skipped list + note "no meaningful sessions found"; skip Step 5 entirely |
| A session's simplified log doesn't fit in context | Windowed read via `chunk_session.py` (Step 3b), unchanged |
| `parse_jsonl_logs.py` fails on a corrupt file | Fall back to reading the raw JSONL with the `read` tool; note degraded quality for that session in its report entries |
| `create_plan` fails | Write Shortcomings/Areas of Improvement/Suggested Improvements directly into the report from the accumulated findings, note the limitation |
| Session ID/path not found | Note it in "Sessions Skipped" with reason "file not found", continue with the rest of the list |
| `/tmp/dagi_simplified.jsonl` already exists | Overwrite — it is a per-session temp file |
| Report file already exists at the target path (re-run within the same second) | Extremely unlikely given second-resolution timestamps; if it happens, overwrite |
| User re-invokes with a session list overlapping a prior report | No cross-run dedup — each invocation's report is self-contained; only within-run duplicates are merged (Step 3d) |
| `datetime_now()` unavailable for a relative time phrase | Fall back to the most recent session's `started_at` as a proxy for "now"; note the limitation in Run Info |
| Ambiguous time ("since 3pm" but it's 2am) | Interpret as "since 3pm yesterday" (most recent occurrence of that time) |
