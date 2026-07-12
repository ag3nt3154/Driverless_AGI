# Plan-Work-Review Resilience — Design

> Status: approved (design phase) | Author: Claude-chan (via brainstorming session) | Date: 2026-07-12

## Problem Statement

The plan-work-review loop (`.dagi/skills/plan-work-review/SKILL.md`, backed by
`tools/spawn_subagent.py` / `tools/_subagent_runner.py`) has two related gaps:

1. **Worker/review subagents have no feedback channel.** If a worker hits an ambiguous
   requirement, a missing dependency, or a genuinely blocking issue, its only options today are to
   guess silently or write it into the handoff report's `## Issues Discovered` section — which the
   main agent only sees *after* the subagent has already spent its full turn (and possibly a full
   retry attempt) working around a problem it could have asked about immediately.
2. **Escalation dead-ends.** There is no path for a subagent to interrupt the loop and get an answer
   from the main agent (or, via it, the user) before continuing. Combined with gap 1, a subagent
   that hits a blocking ambiguity has no better option than silent guessing, wasting a retry attempt
   when it guesses wrong.

Goal: give worker and review subagents a way to raise a blocking question to the main agent
mid-task, without building a new live bidirectional IPC channel, and make the plan's live status
visible to the main agent every iteration without disturbing prompt-cache performance.

## Scope

- **In scope:** a new `escalate_issue` tool for worker/review subagents; file-based escalation
  detection in `tools/_subagent_runner.py`; a new `"escalated"` status branch in
  `tools/spawn_subagent.py`; retry-budget change (3 → 2 total attempts) in
  `.dagi/skills/plan-work-review/SKILL.md`; a live, per-iteration plan status board appended to the
  system prompt tail in `agent/loop.py`.
- **Out of scope:** live synchronous subagent↔main-agent Q&A (would require new `stdin=PIPE` wiring
  and a new resume path); an escalation-count cap or anti-spam mechanism; changes to
  `enter_plan_mode`/`exit_plan_mode`/`complete_plan` behavior (already correct as-is, including
  `task_summary` and auto-branching from the 2026-07-12 git-workflow design).

## Architecture

### A. Escalation Channel

**New tool: `tools/escalate_issue.py`**

```
escalate_issue(question: str, context: str) -> str
```

Available only to worker and review subagents (added to both `.dagi/subagents/worker/subagent_config.yaml`
and `.dagi/subagents/review/subagent_config.yaml` tool lists). When called, it writes a file next to
the subagent's handoff path:

```
<handoff_dir>/{type}_{id}_escalation.md
```

containing the question and context, then returns a short confirmation string to the subagent. The
subagent's `prompt.md` (both worker and review) gains an explicit instruction: **immediately end your
turn after calling `escalate_issue` — do not continue working.**

**Detection: `tools/_subagent_runner.py`**

`_poll_until()` already polls every 2 seconds (`_POLL_INTERVAL`) checking `proc.poll()`. It gains an
additional check on every tick, checked *before* the exit check: does `{handoff_path.parent}/{type}_{id}_escalation.md`
exist? If so:

- Terminate the subprocess (its remaining work is moot once escalated — see Edge Cases).
- Return `{"status": "escalated", "escalation": "<file contents>"}`.

This means escalation is detected within one poll tick (≤2s) regardless of whether the subagent
subprocess obeys the "end your turn" instruction.

**Surfacing to the main agent: `tools/spawn_subagent.py`**

`SpawnSubagentTool.run()` gains a new branch alongside the existing `"ok"` / `"timeout"` / error
handling:

```python
if result["status"] == "escalated":
    return f"[{self._type_name} escalated] {result['escalation']}"
```

The main agent's LLM sees the question and context as a normal tool result — no new plumbing is
needed on the "how does the main agent receive this" side, since it's the same tool-call/tool-result
turn structure as any other subagent outcome.

**Skill-level handling: `.dagi/skills/plan-work-review/SKILL.md`**

Phase 2 Step 4 ("Evaluate and Decide") gains a new branch:

- **If ESCALATED:** Read the question and context. Decide the answer yourself if you can (you have
  full repo access and conversation context the subagent doesn't). Only use `ask_user` if it's a
  genuine judgment call the user must make. Re-spawn the same subagent type for the same subtask,
  including the answer in `custom_instructions`. **This does not consume a retry attempt** — the
  attempt counter is untouched.
- Retry budget language changes from "up to 3 attempts" to **"up to 2 total attempts (1 initial + 1
  retry)"** before marking the subtask `[!]` failed, since escalations are now free and no longer
  need to be absorbed into a padded attempt count.

### B. Live Plan Status Board

**Rendering:** a new function (placed alongside `tools/_plan_parser.py`'s existing
`parse_subtask_statuses()`), e.g. `render_plan_status_board(plan_text: str) -> str`, produces a
compact markdown list:

```
## Plan Status
1. [x] Add escalate_issue tool
2. [~] Wire runner escalation detection
3. [ ] Update plan-work-review skill
4. [!] Add status board renderer
```

reusing the existing marker vocabulary from `parse_subtask_statuses` (`x`=complete, `~`=in_progress,
blank=pending, `!`=failed, `?`=unknown/unparseable) — no new status semantics introduced.

**Integration point:** `agent/loop.py`'s `_assemble_system_string()` currently appends, as its final
conditional block (lines 849–864), an `## Active Plan` section (pointer text + execution-protocol
reminders) whenever `self.config.active_plan_file and not self.config.plan_mode`. The status board
becomes a second sub-block appended immediately after that pointer, inside the same conditional.
Nothing before this tail changes position — this preserves the user's confirmed trade-off: keeping
the changing content at the very end of the prompt protects `cache_prompt`'s hit rate on the large
static prefix (preamble + main system prompt + tools_and_skills), since only content *after* a given
point busts the cache for what follows it, not what precedes it.

**Per-iteration refresh:** `_messages[0]` is currently only rebuilt at mode-transition points
(`__init__`, `_rebuild_for_plan_mode`, `_rebuild_for_normal_mode` — loop.py lines 893, 924, plus
initial construction), never per-iteration. This design adds:

- `self._system_prefix: str` — everything before the Active Plan tail, cached at the same points
  `_messages[0]` is rebuilt today (no new call sites needed, just capturing an extra piece of state
  at existing rebuild points).
- A new step at the top of `AgentLoop.run()`'s main loop (loop.py, immediately after `iteration += 1`
  at line 381, before the API call): if `self.config.active_plan_file` is set, read the plan file,
  call `parse_subtask_statuses` + `render_plan_status_board`, and reconstruct
  `_messages[0]["content"] = self._system_prefix + tail` (pointer section + status board). One file
  read + one regex parse per iteration — cheap, and it never touches `self._system_prefix`, so the
  cached prompt prefix is untouched.
- If `active_plan_file` is `None`, this step is skipped entirely (unchanged behavior from today).

## Error Handling / Edge Cases

1. **Subagent keeps working after calling `escalate_issue`.** Mitigated by (a) explicit prompt.md
   instruction to end the turn immediately, and (b) defense in depth: `_poll_until` detects the
   escalation file within ≤2s of it appearing (not just at process exit) and **terminates the
   subprocess** at that point, bounding wasted work to one poll tick regardless of subagent
   compliance.
2. **Escalation with no `active_plan_file` context** (subagent spawned outside plan-work-review).
   The escalation report is self-contained (question + context written by the subagent); the new
   `"escalated"` branch in `SpawnSubagentTool.run()` works unconditionally, independent of plan
   state. Only the *skill-level* "If ESCALATED" branch is documented in `plan-work-review/SKILL.md`
   — the mechanism itself is not plan-coupled.
3. **Escalation file malformed or unreadable** (partial write, bad encoding, empty). `_poll_until`
   wraps the read in try/except; on failure, falls back to the existing `{"status": "error", ...}`
   contract rather than crashing or introducing a new failure mode.
4. **Malformed plan.md when rendering the status board.** `parse_subtask_statuses` already returns
   `"unknown"` for unparseable subtasks; `render_plan_status_board` prints `[?]` for those rather
   than raising. Worst case: one confusing iteration, never a blocked loop.
5. **Escalation from the review subagent (not worker).** Same file-naming convention
   (`{type}_{id}_escalation.md` with `type=review`), same detection and surfacing path. The skill's
   "If ESCALATED" branch covers both origins; no special-casing needed in `_subagent_runner.py` or
   `SpawnSubagentTool`.
6. **Escalation spam** (a subagent escalates on every attempt). Out of scope for this design — same
   trust boundary as any other subagent behavior today (a broken subagent can already loop or waste
   tokens via other means). No escalation-count cap is added; can be revisited later if it proves to
   be a real problem.

## Testing Approach

**Unit tests:**

- `tools/escalate_issue.py` — correct escalation-file path/contents; required-param validation.
- `tools/_subagent_runner.py::_poll_until` — escalation detected before exit (with subprocess
  termination); escalation detected exactly at exit; no-escalation `"ok"` and `"error"` paths
  unchanged (regression); malformed escalation file → `"error"`, no crash.
- `tools/spawn_subagent.py::SpawnSubagentTool.run` — new `"escalated"` branch formats question/context
  for the main agent; existing `"ok"`/`"timeout"`/error branches unchanged (regression); works
  uniformly for both `worker` and `review` type instances.
- Status board rendering — well-formed plan → correct markers; malformed plan → `[?]` fallback, no
  raise; empty plan (no subtasks yet) → valid empty board.
- Per-iteration refresh in `AgentLoop.run()` — `_messages[0]` reflects a status change between two
  iterations; `self._system_prefix` is byte-for-byte unchanged across iterations (cache-prefix
  guarantee); no `active_plan_file` → tail omitted, matches pre-existing non-plan-mode behavior.

**Integration-level check (manual/lightly scripted):** run `plan-work-review` end-to-end against a
subtask with a deliberately ambiguous acceptance criterion; confirm the worker's escalation reaches
the main agent, gets answered inline, the subagent is re-spawned with the answer, and the retry
attempt counter is untouched (validates "escalations are free" end-to-end).

## Accepted Limitations

- No live synchronous Q&A — escalation is fast-fail (ask once, subagent's turn ends, main agent
  answers and re-spawns). Chosen to avoid new bidirectional subprocess IPC.
- No cap on escalation frequency per subtask.
- Status board content is subtask name + status marker only — no attempt-count or timing detail.
