---
name: improve-yourself
description: End-to-end self-improvement loop — pick a TODO item, research prior art, plan, baseline-test in an isolated snapshot, implement, re-test, analyse impact, and write a ready-to-implement description to TODO.md for the user to apply.
---

# improve-yourself — DAGI Self-Improvement Workflow

This workflow closes the self-improvement loop: pick a TODO item, research existing ideas
and prior art, produce a plan with a concrete test task, run DAGI against that task before
and after the fix (both inside an isolated snapshot — live code is never touched), compare
structural metrics, and write a complete implementation description to TODO.md for the user
to review and apply.

**The user applies the actual code changes.** This workflow's job is to produce a
well-researched, evidence-backed description ready for implementation.

**Invoke with:** `/improve-yourself`

**DAGI_ROOT** is determined from this file's own path:
this file is at `{DAGI_ROOT}/.dagi/workflow/improve-yourself/workflow.md`

The test runner script lives alongside this file:
`{DAGI_ROOT}/.dagi/workflow/improve-yourself/run_test_task.py`

---

## Step 1 — Pick a TODO item

Read `{DAGI_ROOT}/TODO.md`.

Scan `## Work Queue` for incomplete items (bullets that do NOT have a `- [x]` marker
and whose `Next:` field has not been crossed out or replaced with "done").

**Selection priority:**
1. Prefer items tagged `review-item` — they already have a linked plan file to build on.
2. Within the same tag, prefer `priority:high` over `priority:medium` over `priority:low`.
3. Among `review-item` entries at the same priority, prefer those whose `Source:` field
   links to an existing `.dagi/self-review/plan_*.md` (confirmed analysis to extend).
4. If no `review-item` entries remain, fall back to any `priority:high` Work Queue item.

Extract a **kebab-case slug** from the item name (the bold text after the `- **`):
- `Add path resolution warning to memory-ingest SKILL.md` → `memory-ingest-path-warning`
- `Fix redundant skill-load instruction in memory-ingest Step 6` → `memory-ingest-redundant-skill-load`
- `Error Handling & Retries` → `error-handling-retries`

---

## Step 2 — Switch to advanced model

```
switch_model(target="plan")
```

---

## Step 3 — Planning phase

### 3a — Enter plan mode
```
enter_plan_mode(reason="Planning improvement: {item-title}")
```

### 3b — Research phase (before writing the plan)

Before committing to an implementation approach, gather two types of context:

**Internal — query DAGI's memory wiki:**
```
skill("memory-query")
```
Query for concepts directly related to the TODO item. Example queries:
- For a SKILL.md path bug: `"memory skill path resolution G drive"`
- For a redundant tool call: `"skill loading tool call deduplication"`
- For an error handling item: `"API retry backoff error handling"`

Record any relevant findings: existing decisions, known constraints, prior fixes.
If memory-query returns nothing relevant, note that and continue.

**External — web research for prior art:**
```
web_research(task="Research best practices and existing solutions for: {one-sentence description of the TODO item}. Focus on: (1) established patterns used by similar agentic systems, (2) known failure modes and their fixes, (3) any open-source implementations that solve the same problem.")
```

Synthesise the research into a `## Research Notes` section at the top of the plan
document you will write next. Include:
- What DAGI's memory already knows about this area (or "no relevant memory found")
- 2–4 external references or patterns that informed the approach
- Why you chose the implementation direction you did over alternatives found in research

**Only then proceed to write the plan.**

### 3c — Write the plan document

Write to: `{DAGI_ROOT}/.dagi/plans/improvement_{slug}_{YYYY-MM-DD}.md`

If the TODO entry already links to an existing plan file at
`.dagi/self-review/plan_{session-id}.md`, read it first for context.
Your plan document **must extend or refine** that existing analysis — do not discard it.

The plan document must contain exactly these three sections:

1. `## Research Notes` (populated in Step 3b above)
2. `## Section A — Implementation Plan`
3. `## Section B — Test Task Specification`

---

### Section A — Implementation Plan

List every change needed, in the order they should be applied:

```
File: {relative path from DAGI_ROOT}
Change: {exactly what to add/remove/modify — specific, not vague}
Reason: {one sentence — why this addresses the root cause}
```

Be surgical. If the fix is adding one sentence to a SKILL.md, say exactly which sentence
and where it goes. If the fix is editing Python, include the function name and the specific
logic change.

---

### Section B — Test Task Specification

```
Task string: "{exact verbatim task to pass to main.py — no placeholders}"

Baseline expected behaviour:
  - {specific error/failure/retry pattern to expect with current code}
  - {tool call pattern that indicates the bug: e.g., "bash called 3+ times retrying G: paths"}

Improved expected behaviour:
  - {what changes after the fix — one bullet per metric}

Primary structural metrics to watch:
  - error_count: {which error string(s) should disappear, e.g., "PathNotAllowedError", "not allowed"}
  - retry_loops: {which tool and what pattern, e.g., "bash called with G: path 3+ times"}
  - task_completion: {expected outcome — "task completes successfully" vs "task aborts mid-way"}
```

The task string must be **self-contained and unambiguous** — it will be run without human
supervision by `main.py`. Choose a task that exercises the specific code path the fix targets,
ideally one where the bug is reliably reproduced.

**Good test task examples:**
- For a memory-ingest path bug: `"Ingest the file at G:\\My Drive\\black_grimoire\\dagi-memory\\raw\\test.md into the wiki"`
- For a redundant skill-load bug: `"Add a new memory entry for the concept 'context window' to the wiki"`
- For a path guard bug: `"List all wiki files in G:\\My Drive\\black_grimoire\\dagi-memory\\wiki"`

---

### 3d — Exit plan mode
```
exit_plan_mode(summary="Plan written: {N} implementation steps, test task defined — {brief task description}")
```

---

## Step 4 — Switch to default model

```
switch_model(target="default")
```

---

## Step 5 — Freeze a self-contained snapshot

```bash
conda run -n dagi python scripts/dagi_freeze.py freeze --label improve-{slug}
```

Parse the snapshot ID from the output line that reads:
```
[OK] Snapshot saved: {snapshot_id}
```

Save `snapshot_id` — you will need it for every remaining step.

The snapshot now contains: all agent/tool source, `.dagi/skills/`, `config.yaml`, `.env`,
and an empty `.dagi/logs/` directory ready to receive session logs from test runs.

---

## Step 6 — Baseline test (current code)

Run the test task from the plan against the snapshot **as-is** (no changes yet).
The snapshot contains the current live code at freeze time.

```bash
conda run -n dagi python \
  {DAGI_ROOT}/.dagi/workflow/improve-yourself/run_test_task.py \
  "{test_task_from_plan_section_B}" \
  --snapshot-dir {DAGI_ROOT}/snapshots/{snapshot_id}
```

The script prints a final line: `LOG:/absolute/path/to/session_*.jsonl`

Parse that line → save the path as `baseline_log_path`.

If the script exits with code 1, inspect stderr for the reason. Common causes:
- The task string has unescaped quotes — re-escape and retry.
- The conda environment `dagi` is missing a dependency — install it, then retry.

---

## Step 7 — Implement improvement in the snapshot

Apply every change from **Section A** of the plan — but target the **snapshot directory**,
not the live files.

Rule: for every file path in Section A, prepend `{DAGI_ROOT}/snapshots/{snapshot_id}/`.

Examples:
- Plan says edit `.dagi/skills/memory-ingest/SKILL.md`
  → edit `snapshots/{snapshot_id}/.dagi/skills/memory-ingest/SKILL.md`
- Plan says edit `agent/loop.py`
  → edit `snapshots/{snapshot_id}/agent/loop.py`

**Do NOT touch any live files during this step.**

After applying all changes, do a quick sanity check:
```bash
conda run -n dagi python scripts/dagi_freeze.py diff {snapshot_id}
```
Confirm that only the files listed in Section A appear as MODIFIED.

---

## Step 8 — After test (improved code)

Run the exact same task string against the now-modified snapshot:

```bash
conda run -n dagi python \
  {DAGI_ROOT}/.dagi/workflow/improve-yourself/run_test_task.py \
  "{test_task_from_plan_section_B}" \
  --snapshot-dir {DAGI_ROOT}/snapshots/{snapshot_id}
```

Parse the `LOG:` line → save as `after_log_path`.

---

## Step 9 — Switch to advanced model

```
switch_model(target="plan")
```

---

## Step 10 — Analyse both logs (in plan mode)

### 10a — Enter plan mode
```
enter_plan_mode(reason="Analysing improvement impact: {item-title}")
```

### 10b — Simplify both logs

Use the review-session log simplifier on both files:

```bash
conda run -n dagi python \
  {DAGI_ROOT}/.dagi/skills/review-session/parse_jsonl_logs.py \
  {baseline_log_path} \
  --output /tmp/dagi_baseline_simplified.jsonl

conda run -n dagi python \
  {DAGI_ROOT}/.dagi/skills/review-session/parse_jsonl_logs.py \
  {after_log_path} \
  --output /tmp/dagi_after_simplified.jsonl
```

Read both simplified logs with the `read` tool.

### 10c — Extract structural metrics

For each log, count:

| Metric | How to count |
|--------|-------------|
| `error_count` | Tool call records where `result` contains: "Error", "Exception", "not allowed", "failed", "PathNotAllowed" |
| `retry_loops` | Same tool name appearing 3+ consecutive records with similar `input` content |
| `task_completion` | Does the session have a final assistant message that answers the task? (`yes` / `no`) |
| `total_tool_calls` | Total count of tool call records |
| `total_input_tokens` | From `session_end` record |
| `total_cost` | From `session_end` record |

### 10d — Build comparison table

```
| Metric            | Baseline | After | Delta | Signal    |
|-------------------|----------|-------|-------|-----------|
| error_count       | N        | N     | ±N    | primary   |
| retry_loops       | N        | N     | ±N    | primary   |
| task_completion   | yes/no   | yes/no| —     | primary   |
| total_tool_calls  | N        | N     | ±N    | secondary |
| input_tokens      | N        | N     | ±N    | secondary |
| cost ($)          | N        | N     | ±N    | secondary |
```

### 10e — Verdict

- **APPROVED**: ≥1 primary metric improved AND no primary metric worsened.
- **INCONCLUSIVE**: Only secondary metrics changed (token/cost reduction without error/retry change).
- **REJECTED**: Any primary metric worsened (new errors introduced, new retry loops, task no longer completes).

---

## Step 11 — Critical analysis

Still in plan mode. Append a `## Critical Analysis` section to the plan file at
`{DAGI_ROOT}/.dagi/plans/improvement_{slug}_{YYYY-MM-DD}.md`.

Address each of these honestly:

1. **Root cause coverage**: Did the fix address the root cause identified in the original
   TODO observation, or did it only patch the symptom?

2. **Regressions**: Are there any new error patterns in `after_log` that did not appear
   in `baseline_log`? If yes — verdict must be REJECTED regardless of primary metrics.

3. **Surgical precision**: Does the fix change only what is necessary? A one-line change
   to a SKILL.md is better than a five-paragraph rewrite if the root cause is narrow.

4. **Generalisability**: Would this fix help with related items in TODO.md (e.g., if fixing
   memory-ingest, does the same fix apply to memory-add)?

---

## Step 12 — Write implementation description to TODO.md

The workflow's final output is a complete, self-contained implementation description in
`TODO.md`. The user reads this entry and applies the changes themselves. No live files
are modified by this workflow.

### 12a — Append verdict block to TODO.md

Append a new entry to `{DAGI_ROOT}/TODO.md` under `## Self-Improvement Queue`
(create the section if it does not exist):

```markdown
### [{HIGH/MEDIUM/LOW}] {item-title} — {APPROVED/REJECTED/INCONCLUSIVE}

**Workflow run:** {YYYY-MM-DD} | **Snapshot:** `snapshots/{snapshot_id}`
**Baseline log:** `{baseline_log_path}` | **After log:** `{after_log_path}`
**Plan:** [{plan filename}](.dagi/plans/improvement_{slug}_{date}.md)

**Verdict:** {one sentence — what changed and why the verdict was reached}

**Primary metrics:**
| Metric | Baseline | After | Delta |
|--------|----------|-------|-------|
| error_count | N | N | ±N |
| retry_loops | N | N | ±N |
| task_completion | yes/no | yes/no | — |

**Critical analysis:** {2–3 sentences from Step 11}
```

Use a **single `edit` call** to append the entire block.

### 12b — Exit plan mode
```
exit_plan_mode(summary="Verdict written. {verdict} for {item-title}")
```

### 12c — Write implementation description (default model, after plan mode exits)

Read `{DAGI_ROOT}/TODO.md` to find whether a `## Tested Improvements` section
already exists. If it does not exist, create it with this header:

```markdown
## Tested Improvements

> Entries written by the improve-yourself workflow. Each entry is ready to implement —
> apply the exact file changes listed, then mark the item done.
```

Append one entry per workflow run. Read the relevant changed files from the snapshot
(`snapshots/{snapshot_id}/`) to extract the exact diffs, then write:

```markdown
### {item-title} ({APPROVED/REJECTED/INCONCLUSIVE}) — {YYYY-MM-DD}

**Why:** {one sentence — the root cause this addresses, from the original TODO observation}

**Research summary:** {2–3 sentences synthesising what memory-query and web_research found
that informed this approach. Cite any specific patterns or references used.}

**Exact changes to apply:**

{For each file in Section A of the plan:}

#### `{relative file path}`
{Quote the exact before/after diff in a code block. Use the snapshot's edited version
as the "after" — read it and compare against the live file to extract the precise change.}

```diff
- {old lines}
+ {new lines}
```

**Test evidence:**
- Task: `{test_task_string}`
- error_count: {baseline} → {after}
- retry_loops: {baseline} → {after}
- task_completion: {baseline} → {after}

**Verdict rationale:** {2–3 sentences from Step 11 critical analysis explaining whether
the fix is sound, surgical, and generalises to related items}

**To implement:** Apply the diffs above, then remove the originating Work Queue entry
for `{item-title}` (or move it to `## Done` with a `- [x]` checkbox and a one-line summary).
```

Use a **single `edit` call** to append the entry. Do not make multiple partial edits.

---

## Edge Cases

| Situation | Handling |
|-----------|----------|
| `run_test_task.py` exits with code 1 | Check stderr. Most likely: missing conda dep, bad task string escaping, or main.py import error in snapshot. Fix and re-run Step 6 or 8. |
| Baseline and after logs are identical | Run `diff {baseline_log_path} {after_log_path}`. If truly identical, the fix may not have been loaded by the agent — check that the correct snapshot files were edited in Step 7. |
| parse_jsonl_logs.py not found | The review-session skill is at `.dagi/skills/review-session/`. If missing, fall back to reading both raw JSONL files with the `read` tool and counting errors manually. |
| No `session_end` record in log | Session was interrupted. Use tool call counts from what exists; mark task_completion as `no`. |
| TODO.md has no `## Self-Improvement Queue` section | Create it before appending, with header and a one-line description. |
| Plan says to edit a file not in SNAPSHOT_PATHS | The snapshot won't have it. Extend the snapshot: manually copy the file into the snapshot directory with `bash cp`. |
| User wants to test a different item mid-workflow | Stop, restart from Step 1 with the new item. Don't mix artifacts between items. |
