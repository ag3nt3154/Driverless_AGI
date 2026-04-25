---
name: self-improve
description: Two-phase self-improvement loop — analyze last 5 sessions for errors, friction, and missing capabilities, then generate concrete improvement plans for tools, skills, prompts, and config
triggers: self-improve, improve yourself, analyze sessions, review past sessions, reflect on sessions, improve your skills, improve your tools
---

# self-improve — Session Analysis and Improvement Planning

## Purpose

Run DAGI's introspective loop: observe recent sessions for improvement signals,
then generate actionable plans to address them.

**Output location:** All artifacts go to the main DAGI repo root, regardless of
which project invoked this skill:
- Observations: `{DAGI_ROOT}/.dagi/self-improve/observations_YYYY-MM-DD_HH-MM.md`
- Plans: `{DAGI_ROOT}/.dagi/plans/improvement_YYYY-MM-DD_<slug>.md`
- TODO entries: `{DAGI_ROOT}/TODO.md`

**Determine DAGI_ROOT** from this SKILL.md file's own path:
this file lives at `{DAGI_ROOT}/.dagi/skills/self-improve/SKILL.md`,
so DAGI_ROOT is three levels up from this file. Use `find` with pattern
`agent/loop.py` if you need to verify.

Safe by design: all outputs are plan files and TODO entries. **Nothing is
auto-implemented.**

---

## Phase 1: OBSERVE

### Step 1 — Discover the last 5 substantive sessions

Use `find` on `{DAGI_ROOT}/.dagi/logs` with pattern `session_*.jsonl`.

Sort the results by filename **descending** (filenames are timestamped, so most
recent comes last alphabetically — sort descending to get newest first).

Filter: use `bash` to check file size and exclude files **smaller than 5 KB**
(trivially short test sessions with no useful signal). Keep the first 5 files
that pass the size threshold.

If fewer than 5 sessions exist above the threshold, analyze all that do.
If no sessions exist above threshold, report and stop — no output written.

### Step 2 — Extract each session's content

For each selected session file, call:

```
parse_session_log(path="{DAGI_ROOT}/.dagi/logs/{filename}")
```

This returns compact JSON with:
- Conversation flow: user/assistant messages (truncated to 600 chars each)
- Tool call sequence: name, truncated input, truncated result, error flag
- Token counts, cost totals, tool call frequency counts

Do **not** read the raw JSONL file directly — it may be 300KB+ and will flood
the context window.

### Step 3 — Qualitative analysis

Read each session's compact JSON carefully. Look for these improvement signals:

#### 3a. Error signals
- Tool call entries where `"error": true`
- Bash tool results containing non-zero exit codes
- The same tool called 3+ times with identical or similar inputs (retry loop)

#### 3b. Friction — USER QUESTIONING
User messages mid-task (not at session start) that contain:
- "why are you doing this" / "why did you" / "what is this for"
- "why didn't you" / "why not just"
- Any "why" question after the initial task request

These signal the agent took an action the user didn't expect or understand.
The fix is usually: make the agent explain its reasoning before acting, or
change the behavior so it no longer takes that action unsolicited.

#### 3c. Friction — REDO REQUESTS
User messages containing:
- "redo", "try again", "do it again", "start over"
- "that's wrong", "that's not right", "not what I meant"
- "actually, ..." or "wait, ..." (course-correction mid-task)
- The same instruction phrased twice with slight rewording

These signal a misunderstanding between user intent and agent behavior.
The fix is usually: a clarification in AGENTS.md, or a prompt change to make
the agent confirm intent before acting on ambiguous instructions.

#### 3d. Inefficiency signals
- Same file path appears in 3+ consecutive read tool calls
- Input token count exceeds 40k for a task that seems simple
- More than 10 tool calls between two user messages
- `read` used on a full file when `grep` with a pattern would have been precise

#### 3e. Missing capability signals
- Agent writes a temporary Python/bash script to perform a task that could be a tool
- Agent calls `skill("name")` and the result is "skill not found"
- Agent says "I cannot" or "there is no way" about something that seems automatable

### Step 4 — Write the Observations Report

Create the output directory if needed, then write:
`{DAGI_ROOT}/.dagi/self-improve/observations_YYYY-MM-DD_HH-MM.md`

Format:

```markdown
# Observations Report — YYYY-MM-DD HH:MM

## Sessions Analyzed
| File | Tokens In | Tokens Out | Cost |
|------|-----------|------------|------|
| session_....jsonl | N | N | $N |

## Findings

### Finding 1: {Short descriptive title}
**Category:** error | inefficiency | friction-questioning | friction-redo | missing-capability
**Sessions:** {filenames where this appeared}
**Observation:** {2–5 sentences — quote the specific user message or tool result
  that evidences this finding. Be concrete.}
**Impact:** {why this matters — task failure, wasted tokens, user frustration, etc.}

### Finding 2: ...

## Sessions with no significant findings
- session_....jsonl — clean
```

If no findings exist across all sessions, write a brief clean report. Then
**skip Phase 2** and jump directly to Step 8 (report).

---

## Phase 2: PLAN

### Step 5 — Map findings to improvement types

For each finding, determine the improvement type and target:

| Finding category | Improvement type | Likely target |
|-----------------|-----------------|---------------|
| Repeated tool error | `new-tool` or `prompt-change` | `.dagi/tools/` or `AGENTS.md` |
| File re-read inefficiency | `prompt-change` | `AGENTS.md` |
| Missed grep opportunity | `prompt-change` | `AGENTS.md` |
| User questioning (confused by action) | `prompt-change` | `SOUL.md` or `AGENTS.md` |
| Redo request (misunderstood intent) | `prompt-change` | `AGENTS.md` |
| Missing tool for a task type | `new-tool` | `.dagi/tools/` |
| Missing skill for a common workflow | `new-skill` | `.dagi/skills/` |
| High token cost for a simple task | `workflow-fix` or `new-skill` | varies |

Assign each improvement idea:
- **title**: 5–10 words, verb phrase — e.g., "Add clarification step before destructive bash commands"
- **type**: `new-tool` | `new-skill` | `prompt-change` | `workflow-fix`
- **priority**: `high` (task failures, user had to redo) | `medium` (efficiency loss) | `low` (minor)

### Step 6 — Write a plan file for each improvement idea

For each idea, generate a slug: lowercase, hyphens, max 40 chars from the title.
Write the plan to: `{DAGI_ROOT}/.dagi/plans/improvement_YYYY-MM-DD_<slug>.md`

If the file already exists (slug collision), append `-2` to the slug.

**Plan file format:**

```markdown
---
type: improvement-plan
generated_by: self-improve
generated_at: YYYY-MM-DD
idea_type: new-tool | new-skill | prompt-change | workflow-fix
priority: high | medium | low
source_observations: .dagi/self-improve/observations_YYYY-MM-DD_HH-MM.md
status: pending
---

# Improvement Plan: {Idea Title}

## Context
**Finding:** {quote the specific observation — be concrete}
**Impact:** {why this should be fixed}

## Proposed Fix
{1–2 paragraphs describing exactly which file changes, what text, what code}

## Implementation Steps

[For new-tool — include a complete, working BaseTool subclass:]
- [ ] Create `{DAGI_ROOT}/.dagi/tools/{tool_name}.py`:
  ```python
  from agent.base_tool import BaseTool

  class {ToolName}Tool(BaseTool):
      name = "{tool-name}"
      description = "..."
      _parameters = {
          "type": "object",
          "properties": { ... },
          "required": [...],
      }

      def run(self, ...) -> str:
          ...
  ```
- [ ] Restart DAGI and verify via `tool_search("{tool-name}")`
- [ ] Test: {specific example invocation and expected output}

[For new-skill — include complete SKILL.md content:]
- [ ] Create `{DAGI_ROOT}/.dagi/skills/{skill-name}/SKILL.md`:
  ```markdown
  ---
  name: {skill-name}
  description: {one-liner under 120 chars}
  ---
  # {Skill Name}
  {complete step-by-step guidance}
  ```
- [ ] Verify skill appears in next session's skill list

[For prompt-change — quote the exact text to change:]
- [ ] Open `{DAGI_ROOT}/SOUL.md` (or AGENTS.md)
- [ ] Find this text:
  ```
  {exact current text — copy verbatim}
  ```
- [ ] Replace with:
  ```
  {proposed replacement}
  ```

[For workflow-fix:]
- [ ] {specific numbered behavior change with exact file}

## Verification
{Specific scenario: what to invoke, what to observe, what confirms success}

## Rollback
{How to undo — critical for prompt changes that affect every future session}
```

### Step 7 — Append TODO entries to TODO.md

Read `{DAGI_ROOT}/TODO.md`.

Use a **single `edit` call** to append all new entries. Add them under
`## Backlog`, or create a `## Self-Improvement Queue` section if Backlog
is already dense with unrelated items.

Entry format:

```markdown
### [{Priority}] {Idea Title}

**Type:** {idea_type} | **Generated:** YYYY-MM-DD | **Plan:** [improvement_YYYY-MM-DD_slug.md](.dagi/plans/improvement_YYYY-MM-DD_slug.md)

**Root cause:** {one sentence — quote the core observation}

**Quick action:** {the single most important first step, with time estimate if obvious — e.g., "Add 2 lines to AGENTS.md (5 min)" or "Write new BaseTool class (~30 min)"}

- [ ] Review plan at `.dagi/plans/improvement_YYYY-MM-DD_slug.md`
- [ ] Implement
- [ ] Mark plan `status: implemented` when done
```

---

### Step 8 — Report to user

```
## Self-Improvement Run — YYYY-MM-DD HH:MM

**Sessions analyzed:** N
  {list filenames}

**Observations report:** {DAGI_ROOT}/.dagi/self-improve/observations_YYYY-MM-DD_HH-MM.md

### Findings → Plans
1. [high] {Idea Title} → .dagi/plans/improvement_YYYY-MM-DD_slug.md — prompt-change
2. [medium] ...
(none — clean run)

**TODO entries added:** N
```

---

## Edge Cases

| Situation | Handling |
|-----------|----------|
| Fewer than 5 sessions above 5 KB | Analyze all that exist above threshold |
| No sessions above 5 KB threshold | Report and stop — no output written |
| Session JSONL has no `session_end` | `parse_session_log` handles gracefully — still analyze |
| No findings in any session | Write clean observations report, skip Phase 2, report clean run |
| Plan file slug collision | Append `-2` to slug before writing |
| Cannot determine DAGI_ROOT | Halt: "Could not determine DAGI root — verify this skill is at {DAGI_ROOT}/.dagi/skills/self-improve/SKILL.md" |
