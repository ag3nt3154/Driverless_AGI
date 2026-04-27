---
name: review-session
description: Deep-read session logs, analyse tasks/actions/errors/corrections, self-evaluate performance, and write review reports to .dagi/self-review/. Accepts a session ID, time filters, count, or no args (last 5 unreviewed above min length).
triggers: review session, review this session, session review, analyse session, analyze session, review the session, review last session, review unreviewed sessions, review recent sessions, review sessions from last hour
---

# review-session — Session Deep Review

## Purpose

Read DAGI session log(s) in full, understand what happened, evaluate
the agent's performance, and produce structured markdown self-review reports.

Unlike `self-improve` (which skims 5 sessions for patterns), this skill reads
sessions completely and produces thorough, per-session documents.

**Output:** `{DAGI_ROOT}/.dagi/self-review/review_{session-id}.md` per session

**Determine DAGI_ROOT** from this file's own path:
this file is at `{DAGI_ROOT}/.dagi/skills/review-session/SKILL.md`,
so DAGI_ROOT is three levels up.

The chunking script lives alongside this file:
`{DAGI_ROOT}/.dagi/skills/review-session/chunk_session.py`

---

## Parameters

The user may provide any combination of these. All are optional.

| Parameter form | Example | Effect |
|---|---|---|
| Session ID | `2026-04-23_14-59-47` | Review exactly that session; skip all discovery |
| `latest` | `review session latest` | Review the single most recent session |
| Time filter | `last hour`, `last 2 hours`, `today`, `since 3pm`, `since yesterday` | Restrict to sessions started within the window |
| Count | `last 3` | Review at most N sessions (default: 5) |
| Min length | `above 50 nodes` | Override the minimum node count (default: 20) |
| `unreviewed` | `unreviewed` (implied when no ID given) | Exclude sessions that already have a review file |
| `re-review` | `re-review` | Include sessions that already have a review file |
| Combinations | `last 3 unreviewed above 30 nodes last hour` | All filters apply together |

---

## Step 1 — Parse user parameters and build session list

### 1a — Session ID provided
If the user gave a specific session ID (format `YYYY-MM-DD_HH-MM-SS`) or said "latest":
- For an explicit ID: `path = {DAGI_ROOT}/.dagi/logs/session_{id}.jsonl`
- For "latest": run `chunk_session.py --latest {DAGI_ROOT}/.dagi/logs`

Set `session_list = [path]`. Skip to Step 1f (meaningfulness check optional for single sessions).

### 1b — No session ID: get current time if needed
If the user gave a time filter (`last hour`, `today`, `since 3pm`, etc.), call:
```
datetime_now()
```
Parse the returned `utc` and `local` fields to compute the cutoff timestamp.

Time filter parsing:
- `last N hours` / `last hour` → cutoff = now − N hours
- `today` → cutoff = start of today (local midnight)
- `since HH:MM` → cutoff = today at HH:MM local time
- `since yesterday` → cutoff = start of yesterday local time
- `last N minutes` → cutoff = now − N minutes

### 1c — List all sessions
```
conda run -n dagi python {SKILL_DIR}/chunk_session.py --list {DAGI_ROOT}/.dagi/logs
```
Returns a JSON array sorted newest-first. Each entry has `path`, `node_count`,
`started_at`, `model`, etc.

### 1d — Apply filters
Work through the list and apply all active filters:

1. **Min length**: keep sessions with `node_count >= min_length` (default 20; user-overridable)
2. **Time filter**: if a cutoff was computed in 1b, keep sessions where `started_at >= cutoff`
   (both are ISO 8601 strings — compare lexicographically or parse to datetime)
3. **Unreviewed**: unless the user said `re-review`, exclude sessions where
   `{DAGI_ROOT}/.dagi/self-review/review_{session-id}.md` already exists
   (derive session ID: strip `session_` prefix and `.jsonl` suffix from filename)
4. **Count**: take the first N entries after filtering (default 5; user-overridable)

### 1e — No candidates
If the filtered list is empty, report and stop:
> "No sessions found matching the given filters. {brief reason — e.g. 'All recent sessions are already reviewed.' or 'No sessions above 20 nodes in the last hour.'}"

### 1f — Meaningfulness check
For each candidate, quickly decide if it is worth a full review.
Read only the first 10 records of the raw JSONL file (use the `read` tool with a line limit).

**Drop the session** (skip; note the reason) if ALL of the following are true:
- `node_count` < 5, OR
- The only user message is a single word or test phrase ("test", "hello", "hi", "ok"), OR
- There are no tool calls and no assistant content (empty exchange)

**Always keep** sessions that have errors, user corrections, or meaningful tool activity —
even if they look short, those are the most valuable to review.

Skipped sessions are noted in the final summary:
> "Skipping `{session-id}` — trivially short ({N} nodes, no task)."

### 1g — Dispatch
- `session_list` has **one entry** → proceed to Steps 2–6 directly; omit the batch summary
- `session_list` has **multiple entries** → loop Steps 2–6 for each, then print the batch summary below

**Batch summary format** (after all reviews are written):
```
## Batch Review Complete — {date}

Candidates found: {N} | Dropped (unmeaningful): {N} | Reviewed: {N}

Reports written:
- review_{id}.md — {one-sentence task summary}
- review_{id}.md — {one-sentence task summary}

Skipped (unmeaningful):
- {id} — {reason}

Already reviewed (excluded):
- {id}
```

The **session ID** is derived from the filename:
`session_2026-04-23_14-59-47.jsonl` → ID is `2026-04-23_14-59-47`.

---

## Step 2 — Simplify the log and decide reading strategy

First, get the session metadata (model, tokens, cost) and check whether the
simplified log fits in context:

```
conda run -n dagi python {SKILL_DIR}/chunk_session.py <path> --info
```
Save the returned metadata for the report header.

Then run the log simplifier in stats-only mode:
```
conda run -n dagi python {SKILL_DIR}/parse_jsonl_logs.py <path> --stats
```

This returns a JSON object with:
- `original_nodes` — raw line count in the file
- `simplified_nodes` — record count after merging tool pairs and stripping noise
- `estimated_chars` — total character length of the simplified output
- `fits_in_context` — true if `estimated_chars` < 60,000 chars (≈15k tokens)

**Reading strategy:**
- If `fits_in_context` is **true** → **single pass** (Step 3a): generate the
  simplified log and read it directly
- If `fits_in_context` is **false** → **chunked reading** (Step 3b): save the
  simplified log to a temp file and chunk it

---

## Step 3a — Single pass (fits_in_context = true)

Generate the simplified log and save to a temp file:
```
conda run -n dagi python {SKILL_DIR}/parse_jsonl_logs.py <path> --output /tmp/dagi_simplified.jsonl
```

Read `/tmp/dagi_simplified.jsonl` with the `read` tool. Extract all findings
in one pass using the analysis criteria in Step 4. Skip to Step 5.

---

## Step 3b — Chunked reading (fits_in_context = false)

Generate the simplified log to a temp file:
```
conda run -n dagi python {SKILL_DIR}/parse_jsonl_logs.py <path> --output /tmp/dagi_simplified.jsonl
```

Then chunk the **simplified** file:
```
conda run -n dagi python {SKILL_DIR}/chunk_session.py /tmp/dagi_simplified.jsonl
```
(Uses `--chunk-size 60 --overlap 10` by default.)

This returns a JSON array of chunk objects. Each chunk has:
- `chunk_index`, `total_chunks`
- `node_range`: [start, end] inclusive indices into the simplified file
- `is_overlap_start`: true for chunks 2+ (the first `overlap_node_count` records are repeated from the previous chunk)
- `overlap_node_count`: how many leading records are repeated context
- `records`: the simplified node dicts for this chunk

**Process each chunk in order.** Maintain a running `session_notes` dict:

```
session_notes = {
  "tasks": [],
  "agent_actions": [],
  "errors": [],
  "user_corrections": [],
  "user_feedback": []
}
```

For each chunk:

1. If `is_overlap_start` is true, **read the first `overlap_node_count` records
   for context only** — do not add new findings from them. They were already
   processed in the previous chunk.

2. For the remaining (new) records in this chunk, extract findings per Step 4's
   analysis criteria below.

3. Append new findings to `session_notes`.

---

## Step 4 — Analysis criteria

Apply these to all records (single pass) or to the new (non-overlap) records
in each chunk. Populate `session_notes` as you go.

### Tasks
Look at `"type": "message"`, `"entity": "user"` records. The first user
message is usually the primary task. Subsequent user messages may introduce
new tasks or sub-tasks.

Record each distinct task as a short one-sentence description.

### Agent actions
Look at:
- `"type": "tool_call"` records (merged tool pairs in simplified log): note
  the tool name and a brief summary of what was invoked
- `"type": "message"`, `"entity": "assistant"`: note significant decisions or
  explanations in the `content` field
- `"type": "subagent_start"` / `"subagent_end"`: note that a sub-agent was
  spawned and its task

### Errors & problems
- `"type": "tool_call"` records where `"error": true`
- Tool calls with the same `name` and identical or very similar `input`
  appearing 3+ times in a row (retry loop)
- Assistant messages where the agent says it cannot do something

### User corrections
User messages (mid-session, not the first message) containing:
- "no", "wrong", "not right", "that's not", "not what I"
- "redo", "try again", "do it again", "start over"
- "actually", "wait", "instead"
- The same instruction rephrased after an assistant response

Quote the relevant portion of the user message verbatim.

### User feedback
Explicit positive or negative feedback:
- Positive: "good", "perfect", "great", "exactly", "yes that's right"
- Negative: "stop doing X", "don't do that", "I don't want you to"

---

## Step 5 — Enter plan mode and generate the improvement plan

After completing the reading phase (Steps 3a or 3b) and populating
`session_notes`, switch into plan mode to structure the self-evaluation
and improvement items. This ensures the analysis is thorough and well-formed
rather than ad-hoc.

### 5a — Enter plan mode
Call:
```
enter_plan_mode(reason="Analysing session {session-id}: structuring shortcomings, performance review, and improvement plan")
```

### 5b — Draft the analysis (inside plan mode)

In plan mode, write a plan file at:
`{DAGI_ROOT}/.dagi/self-review/plan_{session-id}.md`

Evaluate and write these sections to the plan file:

**Shortcomings** — concrete problems observed:
1. **Task completion**: Was each task completed? If not, why not?
2. **Error handling**: Were errors recovered from gracefully, or retried blindly?
3. **Efficiency**: Redundant steps, repeated file reads, excessive tool calls?
4. **Understanding**: Did corrections indicate misunderstanding? How many?
5. **Token efficiency**: Use `total_input_tokens`; >40k for a simple task is a signal.

**Areas of improvement** — higher-level patterns behind the shortcomings
(e.g. "agent over-reads files", "agent retries without changing approach",
"agent misinterprets terse instructions").

**Improvement items** — concrete, actionable items, one per finding:
- Each item should specify: what to change, where (file/tool/prompt), and why
- Format each as: `[priority: high/medium/low] {verb phrase} — {one-sentence rationale}`
- Examples:
  - `[high] Add a check before re-reading a file already loaded in context — reduces redundant reads`
  - `[medium] Clarify AGENTS.md instruction about terse user corrections — reduces misinterpretation`

### 5c — Exit plan mode
Call:
```
exit_plan_mode(summary="Improvement plan for session {session-id}: {N} shortcomings, {N} improvement items")
```

### 5d — Retain the plan
The plan file at `{DAGI_ROOT}/.dagi/self-review/plan_{session-id}.md` is kept
as a permanent artifact. The improvement items from the plan are included
verbatim in the report's **Suggested Improvements** section (Step 6).

---

## Step 6 — Write the report

Create the output directory if it doesn't exist:
```
mkdir -p {DAGI_ROOT}/.dagi/self-review
```

Write to: `{DAGI_ROOT}/.dagi/self-review/review_{session-id}.md`

Use this format exactly:

```markdown
# Session Review — {session-id}

## Metadata
| Field | Value |
|-------|-------|
| Model | {model} |
| Started | {started_at} |
| Finished | {finished_at or "incomplete"} |
| Total input tokens | {total_input_tokens} |
| Total output tokens | {total_output_tokens} |
| Estimated cost | ${total_cost} |
| Tool calls | {tool_call_counts formatted as "tool×count, tool×count, ..."} |
| Node count | {node_count} |

## Tasks
1. {task description}
2. {task description — omit if only one task}

## What the Agent Did
{2–5 sentence narrative: what the agent actually did, in the order it happened,
with specific tool names and files mentioned}

## Errors & Problems
{Use a bullet list. If none: "No errors recorded."}
- {brief description of the error, with context}

## User Corrections
{Use a bullet list. If none: "No corrections recorded."}
- {quote or close paraphrase of the correction} → {what it addressed}

## User Feedback
{Use a bullet list. If none: "No explicit feedback recorded."}
- [positive/negative] {quote or paraphrase}

## Performance Review
{2–4 sentences: honest self-assessment. What went well, what didn't,
whether the task was completed, how many corrections were needed.
Be specific — reference actual events from the session.}

## Suggested Improvements
{Copy the improvement items verbatim from the plan file written in Step 5b.
If no significant issues: "No improvements identified."}
1. [priority] {improvement item}
2. [priority] {improvement item}

## Plan File
{DAGI_ROOT}/.dagi/self-review/plan_{session-id}.md
```

---

## Edge Cases

| Situation | Handling |
|-----------|----------|
| `incomplete: true` in metadata | Note "session ended without session_end record" in Metadata table and Performance Review |
| No user messages found | Note "no user messages — possibly a sub-agent-only session" in Tasks section |
| Session has only sub-agent records (all `depth > 0`) | Still analyse; note in Metadata that this appears to be a sub-agent session |
| All records are system/assistant (no user turns) | Identify task from system prompt content |
| parse_jsonl_logs.py fails (corrupt file) | Fall back to reading the raw JSONL with the `read` tool; note degraded quality |
| /tmp/dagi_simplified.jsonl already exists | Overwrite — it is a temp file |
| enter_plan_mode unavailable | Skip plan mode; write the shortcomings and improvements inline in the report (note the limitation) |
| Session ID not found | Report: "No session file found at {path}. Run --list to see available sessions." |
| Output file already exists | Overwrite — this is a re-review (or honour `re-review` param) |
| All sessions already reviewed | Report "No unreviewed sessions found matching filters" and stop |
| All candidates dropped as unmeaningful | Report each with reason; stop — no reports written |
| Time filter yields no sessions | Report "No sessions started within the given window" |
| `datetime_now()` unavailable | Fall back to reading timestamps from the most recent session file's `started_at` as a proxy; note the limitation |
| Ambiguous time ("since 3pm" but it's 2am) | Interpret as "since 3pm yesterday" (most recent occurrence of that time) |
