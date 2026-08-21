# DAGI Subagent Architecture Report

**Date:** 2026-08-21  
**Artifacts:**
- [Subagent Reference](https://claude.ai/code/artifact/bd4cba14-ffeb-41d3-aed0-ae295f2c3e8b)
- [Context & Handoff Flows](https://claude.ai/code/artifact/07c7fc2d-b061-4ba6-8fac-f6eceee10393)

---

## Part 1: Subagent Reference

### Architecture Overview

Subagents are spawned as **subprocess isolates**. The parent writes a task file and system prompt to temp files, launches `python -m tools.subagent_main`, and polls stdout for JSON events until exit, escalation, or timeout.

**Execution flow:**

```
Parent tool (main.py)
  → subagent_api.py (API layer)
    → _subagent_runner.py (subprocess spawning)
      → subagent_main.py (entry point)
        → AgentLoop (tool loop)
```

#### Task Envelope

Every task is wrapped by `_task_envelope.py:wrap_envelope()`:

```
## Task
{task body}

---

## Instructions
{custom_instructions, if provided}

---

## Output
{handoff_spec from subagent_config.yaml, or fallback}
```

#### Handoff Pipeline

1. Subagent calls `write_handoff(content=...)` → writes to baked-in path
2. Tool returns sentinel `<<HANDOFF_WRITTEN>>` → loop terminates immediately
3. If no handoff written: one retry prompt, then scrape last assistant text + `_unverified.flag`
4. Runner reads handoff file content and returns it inline as the tool result to the parent

#### Fork Context (Inherited Execution)

Two versions exist for KV-cache prefix reuse:

- **v1** — Used by `compact` only. Single non-streaming API call reusing parent's exact request (messages + tools + extra_body). No tool loop.
- **v2** — Used by tool-bearing subagents when `parent_context` is provided. Inherits parent's message prefix and provider identity. Builds an `InheritedSchemaTool` registry that exposes parent's tool schemas but blocks unauthorized calls. Appends an "Inherited Child Contract" specifying allowed tools and required handoff format.

#### Escalation Path

Subagents with `escalate_issue` can write an escalation file instead of a handoff. The runner detects the sidecar `*_escalation.md` file, terminates the subprocess, and returns `status: "escalated"` with the escalation content. The parent agent can then re-spawn with guidance.

---

### Summary Table

| Subagent | Tool Name | Model Tier | Tools | Root | AGENTS.md |
|----------|-----------|------------|-------|------|-----------|
| plan | `write_plan` | default | read, grep, find, write | project | cwd |
| worker | `run_worker` | default | read, grep, find, write, edit, bash, escalate_issue | project | dagi, cwd |
| review | `review_work` | default | read, grep, find, write, edit, bash, escalate_issue | project | dagi, cwd |
| explore_files | `explore_files` | worker | read, grep, find, write, edit, bash | project | cwd |
| web_research | `web_research` | worker | read, grep, find, write, edit, bash | project | — |
| read-large-text | `read_large_text` | worker | read, grep, find | project | — |
| memory-add | `memory_add` | default | read, grep, find, write, edit | memory_root | — |
| memory-query | `memory_query` | default | read, grep, find | memory_root | — |
| memory-refresh | `memory_refresh` | default | read, grep, find, write, edit, bash | memory_root | — |
| cli | `run_cli` | worker | read, grep, find, write, edit, bash | project | cwd |
| compact | *(internal)* | inherit | *none* | n/a | — |
| wtf | *(internal)* | worker | read, grep, find | project | cwd |

`write_handoff` is always injected regardless of the tools list. `web_search` and `web_fetch` are available when the prompt mentions them but are not declared in every config.

---

### Individual Subagent Details

#### plan

- **Model tier:** default
- **Tool name:** `write_plan`
- **Source:** `.dagi/subagents/plan/`

**System Prompt (prompt.md):**

```
> **CRITICAL:** Do not attempt to perform the task directly. The user's message describes
> what they want planned — your ONLY job is to write the plan document. Do not write code
> to the codebase, do not run shell commands, and do not edit any file except the plan
> document. Treat every user request as a description of what needs to be *planned*, not
> an instruction to execute.

You are a dedicated planning agent. Your sole job is to explore the codebase and produce
a comprehensive plan document.

## Tools available
- read: read any file
- grep: search for text patterns across files
- find: locate files by name or glob pattern
- write: write ONLY to the plan document path provided in your task
- web_research: search the web and fetch pages
- show_plan: emit the finished plan document to the CLI
- ask_user: ask the user a multiple-choice or free-text question

## Output rules
ALL content goes into the plan document. Do NOT write prose responses to the chat.

The plan document must use this exact structure:
# Plan — <short title>
## Context          — What problem is being solved and why.
## Approach         — Chosen strategy and key architectural decisions.
## Files to Modify  — Exact file paths and relevant line numbers.
## Implementation Steps — Ordered, concrete steps.
## Todo List        — One checkbox per discrete action.
## Verification     — How to test/confirm the implementation.

## Exploration rules
- Read files before making claims about their contents.
- Use grep to find all usages of any symbol you plan to touch.
- Keep each todo item atomic: one file change or one shell command.
- When complete: call show_plan, then offer "Approved"/"Request changes" via ask_user.
```

**Config (subagent_config.yaml):**

```yaml
model_tier: default
tools: [read, grep, find, write]
agents_md: [cwd]
default_handoff_spec: >-
  The completed plan document path, and one sentence confirming
  the plan was written and shown via show_plan.
```

**Tools passed:** read, grep, find, write, write_handoff (+ show_plan, ask_user via special registration)

**Handoff:** Calls `write_handoff` confirming the plan was written. The plan document itself is the primary output.

---

#### worker

- **Model tier:** default
- **Tool name:** `run_worker`
- **Source:** `.dagi/subagents/worker/`

**System Prompt (prompt.md):**

```
# Worker Subagent

You are a general-purpose execution agent with full tool access. Your role is to complete
self-contained subtasks efficiently and produce a structured handoff report when done.

## Context
When operating as part of a Plan-Work-Review cycle, your task prompt will include:
- **Plan context**: the Context, Approach, and Notes sections from the active plan
- **Subtask**: the specific subtask (Goal, Requirements, Acceptance Criteria)
- **Custom instructions**: any additional guidance from the main agent

## Guidelines
- Work autonomously — do not ask for clarification unless genuinely ambiguous
- **Do NOT run any tests.** Tests are managed exclusively by the review subagent.
- **Do NOT read test files.** Tests are a hidden oracle.
- If you encounter a blocking ambiguity, call escalate_issue immediately.

## Handoff Report
# Handoff Report: <subtask name>
## What Was Implemented
## What Was Left Undone
## Commands Run — | Command | Exit Code |
## Issues Discovered
```

**Config (subagent_config.yaml):**

```yaml
model_tier: default
tools: [read, grep, find, write, edit, bash, escalate_issue]
agents_md: [dagi, cwd]
default_handoff_spec: >-
  Summarize what was implemented, which files changed, test results,
  and any deviations from the plan or concerns for the reviewer.
```

**Tools passed:** read, grep, find, write, edit, bash, escalate_issue, write_handoff

**Task composition:** Parent's `main.py` loads `plan_utils.py` to extract plan context (Context, Approach, Notes) and the specific subtask block (Goal, Requirements, Acceptance Criteria) from the active plan file.

**Handoff:** Structured report: What Was Implemented, What Was Left Undone, Commands Run, Issues Discovered.

**Escalation:** Has `escalate_issue` — writes sidecar `*_escalation.md`, runner kills subprocess, returns `status: "escalated"`.

---

#### review

- **Model tier:** default
- **Tool name:** `review_work`
- **Source:** `.dagi/subagents/review/`

**System Prompt (prompt.md):**

```
# Review Subagent

You are a review specialist in a Plan-Work-Review cycle. Your role is to objectively
evaluate a worker subagent's output against defined acceptance criteria and unit test results.

## Context
- **Plan context**: Context, Approach, and Notes from the active plan
- **Subtask requirements**: Requirements and Acceptance Criteria
- **Handoff report path**: path to the worker's handoff report
- **Unit test paths**: paths to unit/integration test files

## Responsibilities
- Read the handoff report in full
- Run the unit tests and record each result
- Evaluate against every acceptance criterion
- Identify bugs, logic errors, edge cases, style/security/performance concerns
- Check consistency with the Approach and Context

## Guidelines
- **Do NOT modify any code or files under review.** Write/edit access solely for the report.
- PASS: all unit tests passing AND all criteria met
- FAIL: at least one test failing OR criterion not met
- If blocked by ambiguity, call escalate_issue immediately.

## Review Report
# Review Report: <subtask name>
## Verdict — PASS / FAIL
## Test Results — | Test | Result | Notes |
## Criteria Evaluation — | Criterion | Met? | Notes |
## Issues Found — Numbered, with Severity / Location / Description / Recommendation
## Summary — One paragraph.
```

**Config (subagent_config.yaml):**

```yaml
model_tier: default
tools: [read, grep, find, write, edit, bash, escalate_issue]
agents_md: [dagi, cwd]
default_handoff_spec: >-
  State pass/fail per acceptance criterion, test results, and any
  issues found (critical/important/minor) with a clear verdict.
```

**Tools passed:** read, grep, find, write, edit, bash, escalate_issue, write_handoff

**Task composition:** `review_utils.py` composes: plan context, subtask requirements/criteria, worker's handoff report path, and unit test file paths.

**Handoff:** Verdict (PASS/FAIL), Test Results table, Criteria Evaluation table, Issues Found list, Summary.

---

#### explore_files

- **Model tier:** worker
- **Tool name:** `explore_files`
- **Source:** `.dagi/subagents/explore_files/`

**System Prompt (prompt.md):**

```
You are a codebase exploration agent. Your job is to locate relevant code and return
precise file-line citations — not to explain or summarize at length.

## Tools available
- read — read file contents at specific paths and line ranges
- grep — search for patterns across files
- find — locate files by glob pattern
- bash — run shell commands (e.g. dir, tree, python -m pytest --collect-only)
- edit — make small, targeted edits when the task explicitly asks for a fix

## Search strategy
1. Start broad — use find with glob patterns and grep with regex
2. Go narrow — read only the specific line ranges
3. Check multiple locations — a symbol may appear under different names
4. Parallelize — issue multiple independent tool calls in one turn

## Output rules
- Do NOT modify any source files.
- Every finding MUST be anchored to a path:line_start-line_end citation.
- Keep prose minimal. Do NOT write a plan or implementation steps.

## Handoff
# Exploration: <topic>
## Summary — One paragraph (≤80 words)
## Citations — path/to/file.py:10-45 — what this range contains
## Notes — Any important caveats (≤5 bullet points)
```

**Config (subagent_config.yaml):**

```yaml
model_tier: worker
tools: [read, grep, find, write, edit, bash]
agents_md: [cwd]
default_handoff_spec: >-
  A structured exploration report with a summary, file:line
  citations for every finding, and notable caveats.
```

**Tools passed:** read, grep, find, write, edit, bash, write_handoff

**Handoff:** Summary (≤80 words), Citations (file:line anchors), Notes (≤5 bullets).

---

#### web_research

- **Model tier:** worker
- **Tool name:** `web_research`
- **Source:** `.dagi/subagents/web_research/`

**System Prompt (prompt.md):**

```
You are a focused web research agent. Answer the research question using web_search
and web_fetch only.

Guidelines:
- Issue 1-3 targeted searches.
- Fetch the most relevant URLs (limit to 3 fetches).
- Synthesise findings into a concise Markdown report.
- End with a ## Sources section listing every URL used.
- Do NOT speculate beyond what the sources say.
```

**Config (subagent_config.yaml):**

```yaml
model_tier: worker
tools: [read, grep, find, write, edit, bash]
agents_md: []
default_handoff_spec: >-
  A synthesized answer to the research question with source URLs
  and key excerpts.
```

**Tools passed:** read, grep, find, write, edit, bash, write_handoff (prompt instructs web_search/web_fetch only)

**Handoff:** Synthesized markdown report with `## Sources` section.

---

#### read-large-text

- **Model tier:** worker
- **Tool name:** `read_large_text`
- **Source:** `.dagi/subagents/read-large-text/`

**System Prompt (prompt.md):**

```
# Read Large Text

You are a large text file reader. Read a large text file in chunks and produce
a structured summary digest.

## Process
1. Read in chunks using read(path, offset, limit) with ~2000 lines per chunk.
2. For each chunk: section heading, summary in context of all prior sections,
   key excerpts with line numbers, line range, token estimate.
3. Maintain an accumulative summary.
4. Verification pass: review claims, verify critical details with grep and read.
5. Deliver via write_handoff.

## Output Format
[File: <filename> | <N> sections | full text cached: <source_path>]

## <Section> (lines <start>-<end>, ~<T> tokens)
**Summary:** ...
**Key excerpts:**
- L<N>: "<verbatim quote>"

---
Full text: <source_path>
Use read(path, offset, limit) for verbatim content from any section.
```

**Config (subagent_config.yaml):**

```yaml
model_tier: worker
tools: [read, grep, find]
agents_md: []
default_handoff_spec: >-
  A sectioned digest with line ranges, token estimates, and key
  excerpts per section.
```

**Tools passed:** read, grep, find, write_handoff

**Handoff:** Sectioned digest with line ranges, token estimates (~chars/4), and key excerpts with verbatim quotes.

---

#### memory-add

- **Model tier:** default
- **Tool name:** `memory_add`
- **Source:** `.dagi/subagents/memory-add/`
- **Root:** `memory_root` (wiki directory)

**System Prompt (prompt.md):**

```
# Memory Add Subagent

You are a specialist knowledge-filing agent. Follow the canonical protocol in
.dagi/skills/memory-add/SKILL.md exactly, with these DAGI-specific tool mappings:

| Protocol action    | DAGI tool                        |
|--------------------|----------------------------------|
| Read a file        | read(path)                       |
| Search for content | grep(pattern, path)              |
| Find files         | find(pattern, path)              |
| Write a new file   | write(path, content)             |
| Edit existing      | edit(path, old_text, new_text)   |

## Parameters
- task — the content to file (required)
- category — projects | todos | knowledge | events (required)
- deadline — for todos (optional)
- frequency — for todos, default one-off (optional)
- date — for events, default today (optional)
```

**Config (subagent_config.yaml):**

```yaml
model_tier: default
root: memory_root
tools: [read, grep, find, write, edit]
agents_md: []
default_handoff_spec: >-
  Confirmation of what was filed, path, and what index files were updated.
```

**Tools passed:** read, grep, find, write, edit, write_handoff (file access restricted to `memory_root`)

**Handoff:** Confirmation of what was filed, path written, index files updated.

---

#### memory-query

- **Model tier:** default
- **Tool name:** `memory_query`
- **Source:** `.dagi/subagents/memory-query/`
- **Root:** `memory_root` (wiki directory)

**System Prompt (prompt.md):**

```
# Memory Query Subagent

You are a specialist research agent with read-only access to the memory wiki.
Follow the canonical protocol in .dagi/skills/memory-query/SKILL.md exactly.

| Protocol action    | DAGI tool            |
|--------------------|----------------------|
| Read a file        | read(path)           |
| Search for content | grep(pattern, path)  |
| Find files         | find(pattern, path)  |

## Parameters
- task — the question or topic to look up (required)
- scope — narrows search to a subtree (optional)
```

**Config (subagent_config.yaml):**

```yaml
model_tier: default
root: memory_root
tools: [read, grep, find]
agents_md: []
default_handoff_spec: >-
  A synthesized answer with [[wikilink]] citations to source pages.
```

**Tools passed:** read, grep, find, write_handoff (read-only access to `memory_root`)

**Handoff:** Synthesized answers with `[[wikilink]]` citations.

---

#### memory-refresh

- **Model tier:** default
- **Tool name:** `memory_refresh`
- **Source:** `.dagi/subagents/memory-refresh/`
- **Root:** `memory_root` (wiki directory)

**System Prompt (prompt.md):**

```
# Memory Refresh Subagent

Wiki maintenance agent. Interactive triage: presents each issue to user,
waits for decision before acting.
```

**Config (subagent_config.yaml):**

```yaml
model_tier: default
root: memory_root
tools: [read, grep, find, write, edit, bash]
agents_md: []
```

**Tools passed:** read, grep, find, write, edit, bash, write_handoff (access restricted to `memory_root`)

---

#### cli

- **Model tier:** worker
- **Tool name:** `run_cli`
- **Source:** `.dagi/subagents/cli/`

**System Prompt (prompt.md):**

```
ConPTY terminal subagent. Final assistant reply is the result. Each task independent.
```

**Config (subagent_config.yaml):**

```yaml
model_tier: worker
tools: [read, grep, find, write, edit, bash]
agents_md: [cwd]
```

**Tools passed:** read, grep, find, write, edit, bash, write_handoff

**Handoff:** Final assistant reply is the result.

---

#### compact

- **Model tier:** inherit (same model as parent)
- **Source:** `.dagi/subagents/compact/`
- **Fork context:** v1 (single API call, no tool loop)

**System Prompt (prompt.md):**

```
You are a precise technical summariser. Rules:
- Preserve every file path, function name, tool call, result, decision, error, resolution.
- Carry forward prior compaction summaries.
- End with ### Files Read/Modified section.
- Output ONLY the summary.
```

**Config (subagent_config.yaml):**

```yaml
model_tier: inherit
tools: []
agents_md: []
```

**Tools passed:** None (single API call, no tool loop)

**Execution:** Single non-streaming `client.chat.completions.create()` call. Reuses parent's exact request (messages + tools + extra_body) via v1 fork context for KV-cache hit. Writes summary directly to handoff file.

---

#### wtf

- **Model tier:** worker
- **Source:** `.dagi/subagents/wtf/`
- **Fork context:** v2 inherited (fork_mode="stable")

**System Prompt (prompt.md):**

```
Read-only diagnostic investigator. Bare /wtf means infer problem from inherited context.
Required output: exactly three level-two sections:
## Description
## Error Report
## Suggested Fix
```

**Config (subagent_config.yaml):**

```yaml
model_tier: worker
tools: [read, grep, find]
required_sections: [Description, Error Report, Suggested Fix]
agents_md: [cwd]
```

**Tools passed:** read, grep, find, write_handoff (via InheritedSchemaTool registry — all parent tool schemas visible but only allowed tools execute)

**Handoff validation:** `_validate_final_handoff()` checks: no preamble before first section, all required sections present, no duplicates, no unknown sections, each body non-empty, correct order. One retry on failure.

**Staleness check:** After subprocess exits, parent checks `surface.generation != fork.parent_surface_generation` → result marked "stale" and discarded.

**Parent integration:** Does NOT inline the full report. Appends a lightweight reference message pointing to the handoff file and branch ID.

---

## Part 2: Context Build & Handoff Flows

### Pipe Mode Context Build (Normal)

Used by: `explore_files`, `worker`, `review`, `plan`, `web_research`, `cli`, `memory-*`, `read-large-text`

The subagent runs as a **fresh subprocess** with its own system prompt and tool registry. No parent conversation prefix is inherited.

#### Parent Side (loop.py)

**1. Parent loop enters turn T, step S** (`agent/loop.py:994-1016`)

The parent's `run()` opens a turn, logs the user message, then enters the step loop:

```
[turn/start]      {turn: T}
[step/start]      {turn: T, step: S}
[user/message]    {turn: T, step: 0, role: "user", content: "..."}  ← appended to surface
```

**2. Model returns tool call** (`agent/loop.py:1197-1222`)

```
[assistant/message]  {turn: T, step: S, message: {role: "assistant", tool_calls: [...]}}
[tool/call]          {turn: T, step: S, call_id: "call_abc", name: "explore_files", arguments: "..."}
```

**3. Tool dispatched** (`agent/loop.py:1282-1283` → `main.py:56-85`)

Registry dispatches to the BaseTool subclass's `run()`, which calls `subagent_api.run_subagent()`.

#### API Layer (subagent_api.py)

**4. Resolve preset options** (`tools/subagent_api.py:162-180`)

`_resolve_subagent_options()` loads `prompt.md` and `subagent_config.yaml`. Returns: prompt text, tools list, model_tier, handoff_spec, agents_md list.

```
prompt   ← .dagi/subagents/{type}/prompt.md
tools    ← subagent_config.yaml → tools: [read, grep, find, ...]
tier     ← subagent_config.yaml → model_tier: worker|default
hs       ← subagent_config.yaml → default_handoff_spec: "..."
```

**5. Build task envelope** (`tools/subagent_api.py:289-291` → `tools/_task_envelope.py:23-36`)

`wrap_envelope()` composes the final task text:

```
## Task
{task body from tool call args}

---

## Instructions                    ← only if custom_instructions provided
{custom_instructions}

---

## Output                          ← always present
{handoff_spec from config, or fallback}
```

**6. Prepare inherited context (branch recording)** (`tools/subagent_api.py:220-248`)

`_prepare_inherited_context()` generates a branch ID and records the branch point:

```
[branch/start] {
  branch: "explore_files_a1b2c3d4",
  parent_branch: "main",
  turn: T,  step: S,
  parent_cut_seq: <last surface node seq>,
  parent_surface_generation: <int>
}
```

**7. Build extra argv** (`tools/subagent_api.py:308-318`)

```
argv: [python, -m, tools.subagent_main,
  --subagent-type, explore_files,
  --task-file, /tmp/dagi_task_xxx.txt,
  --handoff, .dagi/handoffs/explore_files_a1b2c3d4.md,
  --project, C:\Users\alexr\project,
  --system-prompt-file, /tmp/dagi_prompt_xxx.md,
  --tools, read,grep,find,write,edit,bash,
  --model-tier, worker,
  --fork-context, /tmp/dagi_fork_context_xxx.json]
```

#### Runner Layer (_subagent_runner.py)

**8. Spawn subprocess** (`tools/_subagent_runner.py:172-249`)

Writes task to temp file, spawns `python -m tools.subagent_main` with stdout piped. Daemon thread reads JSON events. Runner polls until exit, escalation, or timeout.

#### Subprocess Entry (subagent_main.py)

**9. Entry point routing** (`tools/subagent_main.py:689-741`)

`main()` parses args and routes: v2 fork → `run_forked_subagent_mode()`, no fork → `run_subagent_pipe_mode()`, v1 fork → `run_forked_compact_mode()`.

**10. Build config and registry (pipe mode)** (`tools/subagent_main.py:615-675`)

```
System prompt assembly (_build_subagent_system_prompt):
  1. Base prompt ← prompt.md
  2. If agents_md includes "dagi" → append DAGI_ROOT/AGENTS.md
  3. If agents_md includes "cwd"  → append project/AGENTS.md
  Joined with "\n\n---\n\n"

Tool registry (build_subagent_registry):
  1. Load subagent_config.yaml → tools list
  2. If root: memory_root → restrict allowed_roots to wiki dir only
  3. Instantiate tools via _tools_from_list()
  4. Always inject WriteHandoffTool(handoff_path) at the end
```

**11. Create AgentLoop and run task** (`tools/subagent_main.py:670-686`)

```python
AgentLoop(
  config=typed_config,            # worker or default model
  callbacks=pipe_callbacks,       # emit JSON events to stdout
  initial_messages=[{role: "system", content: system_prompt}],
  _registry=registry,             # restricted tool set
)
loop.run(enveloped_task)          # task text from step 5
```

> **Key insight:** In pipe mode, the subprocess gets a completely fresh conversation. Its only context is the system prompt (prompt.md + AGENTS.md) and the enveloped task. No parent conversation history.

#### Turn/Step/Branch Coordinate Summary

| Event | Branch | Turn | Step | Where |
|-------|--------|------|------|-------|
| `turn/start` | main | T | — | Parent loop.run() |
| `user/message` | main | T | 0 | Parent loop.run() — pre-step |
| `step/start` | main | T | S | Parent loop iteration |
| `assistant/message` | main | T | S | Parent — model response |
| `tool/call` | main | T | S | Parent — before dispatch |
| `branch/start` | main | T | S | subagent_api — fork point |
| *(child events)* | *child branch* | *child T* | *child S* | *Subprocess — own log* |
| `tool/result` | main | T | S | Parent — handoff inlined |
| `step/end` | main | T | S | Parent loop iteration end |

---

### Inherited Mode (v2 Fork Context)

Used by: `wtf` (fork_mode="stable"), and any subagent when `parent_context` is provided. The child inherits the parent's conversation prefix and KV-cache.

#### Fork Capture (Parent Side)

**1. Capture parent fork** (`agent/loop.py:478-519`)

`capture_parent_fork(branch_id, mode)` freezes the parent's state:

- **mode="spawn"** (default): Uses `_last_request_snapshot` — the exact API request from the most recent provider call. Captures messages, tools, model, extra_body at the moment the model was last called.
- **mode="stable"** (used by wtf): Requires the loop to be idle. Rebuilds the full request from scratch via `_build_request_messages()`.

**2. Record BRANCH_START with coordinates** (`agent/loop.py:507-519`)

```
[branch/start] {
  branch: "wtf_a1b2c3d4",
  parent_branch: "main",
  turn: T,
  step: S,
  parent_cut_seq: <last surface node>,
  parent_surface_generation: <int>
}
```

**3. Build v2 fork context file** (`agent/parent_context.py:71-94`)

`build_fork_context_v2()` assembles the JSON file. Validates no secret fields leak. Credentials resolved separately by the child.

```json
{
  "version": 2,
  "branch": {
    "id": "wtf_a1b2c3d4",
    "parent_cut_seq": 42,
    "parent_surface_generation": 3
  },
  "request": {
    "model": "anthropic/claude-sonnet-4-20250514",
    "messages": [
      {"role": "system", "content": "..."},
      {"role": "user", "content": "..."},
      {"role": "assistant", "content": "...", "tool_calls": [...]},
      {"role": "tool", "tool_call_id": "...", "content": "..."}
    ],
    "tools": [...],
    "parallel_tool_calls": false,
    "extra_body": {"reasoning": {"effort": "medium"}},
    "base_url": "https://openrouter.ai/api/v1"
  },
  "child": {
    "type": "wtf",
    "allowed_tools": ["read", "grep", "find", "write_handoff"]
  }
}
```

#### Subprocess Side (run_forked_subagent_mode)

**4. Resolve credentials locally** (`tools/subagent_main.py:281-318`)

`_build_inherited_config()` takes model name and base_url from fork context but resolves API keys from the child's own environment.

**5. Build inherited tool registry** (`tools/subagent_main.py:388-405` → `agent/inherited_registry.py:42-54`)

Two registries: an *implementation* registry with actual tool implementations, and an *inherited* registry wrapping parent's tool schemas with access control.

```
Every parent tool schema appears in the registry (preserving the
provider's tool list for KV-cache hit), but only allowed tools
actually execute. Blocked calls return:
  "Error: Access blocked for tool 'bash' in subagent 'wtf'.
   Allowed tools: read, grep, find, write_handoff"
```

**6. Build inherited task with contract** (`tools/subagent_main.py:458-480`)

```
{prompt.md content}

---

## Inherited Child Contract
- Effective allowed tools: read, grep, find, write_handoff
- Calls to any other tool are blocked.
- Complete the task, then call write_handoff as your final action.
- Required format: ## Description, ## Error Report, ## Suggested Fix.

---

## Task
{task text}

---

## Output
{handoff_spec}
```

**7. Create AgentLoop with inherited prefix** (`tools/subagent_main.py:406-416`)

```python
AgentLoop(
  config=inherited_config,
  callbacks=pipe_callbacks,
  initial_messages=parent_messages,      # parent's FULL history
  _registry=inherited_registry,          # schema-preserving + access control
  _system_prompt_override=parent_system, # parent's system prompt
  _preserve_request_prefix=True,         # no wiki/board injection
)
```

Messages sent to provider:
```
[0] system: parent's original system prompt     ← KV-cache warm prefix
[1] user: parent's first message                ← continued...
[2] assistant: parent's response
...                                             ← full history
[N] user: inherited task + contract             ← NEW: child's task
```

> **KV-cache reuse:** The child sends the parent's exact message prefix (byte-identical), so the provider can reuse the warm KV cache. The child only pays for new tokens (task + contract) plus its own generation.

#### Handoff Validation

**8. Validate handoff structure** (`tools/subagent_main.py:429-443`)

Validation rules: no preamble, all required sections present, no duplicates, no unknown sections, each body non-empty, correct order. One retry on failure.

**9. Staleness check** (`tools/subagent_api.py:327-337`)

After subprocess exits, parent checks `surface.generation != fork.parent_surface_generation`. If changed → result marked "stale" and discarded.

---

### Compact (v1 Fork Context)

Triggered automatically when `prompt_tokens > context_window - reserve_tokens`.

#### Tail Boundary Computation

**1. Collect all (turn, step) pairs** (`agent/loop.py:706-722` → `tools/compact/_tail_boundary.py:43-90`)

```
steps = [(1,1), (1,2), (1,3), (2,1), (2,2), (2,3), (2,4)]

avg_tokens_per_step = prompt_tokens / len(steps)
keep_count = keep_recent_tokens / avg_tokens_per_step
keep_count = clamp(keep_count, 1, len(steps))

Result for keep_count=3:
  middle_steps = [(1,1), (1,2), (1,3), (2,1)]  ← will be summarized
  tail_steps   = [(2,2), (2,3), (2,4)]          ← kept verbatim
```

#### Fork Context Construction

**2. Record retroactive BRANCH_START** (`agent/loop.py:834-847`)

Branch anchored at the **last summarized step**, not the current step:

```
[branch/start] {
  branch: "compact_e5f6g7h8",
  parent_branch: "main",
  turn: 2,  step: 1,                    ← last step in middle_steps
  parent_cut_seq: <STEP_END seq of (2,1)>,
  parent_surface_generation: 3
}
```

**3. Reconstruct inherited prefix** (`agent/loop.py:850-858` → `agent/context_spec.py:183-201`)

`spec_for_branch()` builds a `ContextSpec` for the compact branch including the full ancestor chain. `reconstruct()` collects surface events up to the fork point, honoring replace operations (prior compactions).

```
ContextSpec:
  segments: [
    BranchSegment(branch="main", turns=[(0,[0]), (1,[1,2,3]), (2,[1])])
  ]

reconstruct(log, spec) → (system_header, prefix_messages)
```

**4. Build v1 fork context** (`tools/subagent_api.py:80-107`)

```json
{
  "version": 1,
  "branch": {
    "id": "compact_e5f6g7h8",
    "parent_cut_seq": 42,
    "parent_surface_generation": 3
  },
  "request": {
    "model": "anthropic/claude-sonnet-4-20250514",
    "messages": [
      {"role": "system", "content": "parent system prompt"},
      "... prefix messages up to cut point ..."
    ],
    "tools": [...],
    "parallel_tool_calls": false,
    "extra_body": {...}
  }
}
```

#### Subprocess Execution

**5. Single API call (no tool loop)** (`tools/subagent_main.py:532-612`)

`run_forked_compact_mode()` makes exactly one non-streaming API call:

```
Messages to provider:
  [0] system: parent's system prompt        ← KV-cache warm prefix
  [1] user: first user message
  ...                                       ← messages up to cut point
  [N] user: compact prompt + spec           ← "Summarize the conversation above..."

→ Single non-streaming API call
→ Validates: no tool_calls, not truncated, not empty
→ Retries on connection errors (3x, exponential backoff)
→ Writes summary directly to handoff file
```

#### Atomic Acceptance

**6. Validate and atomically replace** (`agent/loop.py:881-923`)

Validation checks:
- `result.is_ok` and `handoff_text` is non-empty
- `surface.generation == pre_gen` (surface didn't change during compact)
- `first_summarized_seq` still on surface
- `last_summarized_seq` still on surface

If any check fails → compaction silently abandoned.

**7. CONTEXT_COMPACTION replaces surface nodes** (`agent/loop.py:902-913`)

```
[context/compaction] {
  summary: "[CONTEXT SUMMARY — conversation compacted (generation 1)]
            {summary text from compact subagent}",
  removed: 4,
  generation: 1,
  branch: "compact_e5f6g7h8",
  handoff: ".dagi/handoffs/compact_e5f6g7h8.md"
}
surface_op: ("replace", first_summarized_seq, last_summarized_seq)

After replacement, the surface looks like:
  [compaction_event]  ← replaces old nodes 1..N
  [tail_step_1]       ← preserved verbatim
  [tail_step_2]       ← preserved verbatim
  [tail_step_3]       ← preserved verbatim

Surface generation: 3 → 4
```

**8. Sync messages from log** (`agent/loop.py:925-927`)

`_sync_messages()` rebuilds `_messages` from the log. The compaction summary projects as `role: "user"` (to avoid breaking the assistant→tool pairing rule).

> **Cache-aware design:** The compact subagent reuses the parent's KV-cache prefix. After compaction, the parent's next API call sees a different prefix (summary replaces old messages), which invalidates the KV cache. This is why `surface.generation` increments — it tells in-flight forks that their cached prefix is stale.

---

### Handoff & Escalation Flows

#### Normal Handoff (write_handoff)

**1. Child calls `write_handoff(content="...")`** (`tools/write_handoff/_write_handoff.py:42-47`)

Writes content verbatim to the baked-in handoff path. Returns `"Handoff written. <<HANDOFF_WRITTEN>> Your turn ends now."`

**2. Sentinel detected → loop short-circuits** (`agent/loop.py:1284-1291`)

In `_dispatch_tool_calls()`, result is checked for `<<HANDOFF_WRITTEN>>`. If found AND tool name is `write_handoff`, calls `_handle_write_handoff()` which does bookkeeping and returns — no further tool calls or API turns.

```
[tool/result]  {turn: T, step: S, call_id: "...", content: "Handoff written."}
               ← sentinel stripped before logging

_handle_write_handoff():
  callbacks.on_handoff()      ← notify parent TUI
  _bookkeep_tool_call()       ← filter output, log tool/result, sync messages
  _finalize_turn()            ← record usage, emit token callback
  return result               ← short-circuit out of run()
```

**3. Subprocess exits cleanly** (`tools/subagent_main.py:678-686`)

After `loop.run()` returns, `_ensure_handoff()` confirms the file exists. Subprocess emits `{"type": "done"}` and exits.

**4. Runner detects exit → reads handoff** (`tools/_subagent_runner.py:140-153`)

```
proc.poll() → exit code 0
handoff_path.exists() → True
_check_unverified() → False (normal handoff)

return {"status": "ok", "handoff": ".dagi/handoffs/explore_files_a1b2c3d4.md"}
```

**5. API layer reads handoff text** (`tools/subagent_api.py:110-123`)

`_build_result()` auto-reads the handoff file into `SubagentResult.handoff_text`. Tool's `run()` calls `format_handoff_result()` to inline it.

**6. Parent logs tool result with handoff content** (`agent/loop.py:1356-1367`)

```
[tool/result] {
  turn: T, step: S, call_id: "call_abc",
  content: "Subagent completed. Handoff written to: ...
            --- Handoff content ---
            # Exploration: ..."
}
```

#### Degrade Path (No write_handoff Called)

1. `_ensure_handoff()` detects handoff file is missing
2. Retry prompt: `"You ended without calling write_handoff. Call it now with your complete report."`
3. If still missing: `_extract_final_assistant_text()` scrapes last assistant message, writes to handoff file with `_unverified.flag` sidecar
4. Runner returns `{"status": "ok_unverified", "handoff": "..."}`
5. Parent sees: `"⚠️ UNVERIFIED HANDOFF — the subagent exited without calling write_handoff. The content below was scraped..."`

#### Escalation Path

**1. Child calls `escalate_issue(question, context)`** (`tools/escalate_issue/_escalate_issue.py:52-64`)

Writes sidecar file: `.dagi/handoffs/{type}_{id}_escalation.md`

```
# Escalation

## Question
{question}

## Context
{context}
```

Returns `"Escalation recorded. End your turn now."`

**2. Runner detects escalation file** (`tools/_subagent_runner.py:122-139`)

`_poll_until()` checks for escalation sidecar every 2 seconds. When found:
- Terminates subprocess (SIGTERM, then SIGKILL after 5s)
- Cleans up state
- Returns `{"status": "escalated", "escalation": "..."}`

**3. Parent tool returns escalation**

`dispatch_status_result()` formats as: `"[worker escalated]\n\n{escalation content}"`

#### Timeout & Resume

**1. Timeout reached** (`tools/_subagent_runner.py:152`)

Subprocess is **not killed** — stays in `_active` so it can be resumed. Returns `{"status": "timeout", "pid": 12345}`.

**2. Parent can resume** (`tools/_subagent_runner.py:252-261`)

`resume_subagent(pid, extra_seconds)` looks up the process and continues polling.

---

## Key Source Files

| File | Role |
|------|------|
| `.dagi/subagents/{type}/prompt.md` | System prompt per subagent |
| `.dagi/subagents/{type}/subagent_config.yaml` | Model tier, tools, agents_md |
| `.dagi/subagents/{type}/main.py` | BaseTool subclass, task composition |
| `tools/subagent_api.py` | Central API: preset loading, envelope, fork context, runner invocation |
| `tools/_subagent_runner.py` | Subprocess spawning, polling, escalation detection |
| `tools/subagent_main.py` | Subprocess entry point: routing, registry, loop creation |
| `tools/_task_envelope.py` | `wrap_envelope()` — ## Task / ## Instructions / ## Output |
| `tools/write_handoff/_write_handoff.py` | WriteHandoffTool — writes content, returns sentinel |
| `tools/_handoff_format.py` | `format_handoff_result()`, `dispatch_status_result()` |
| `tools/escalate_issue/_escalate_issue.py` | EscalateIssueTool — writes sidecar escalation file |
| `agent/loop.py` | AgentLoop — run(), dispatch, compact, fork capture |
| `agent/session_log.py` | Append-only event log with invariant enforcement |
| `agent/session_events.py` | Event types: TURN_START, STEP_START, BRANCH_START, etc. |
| `agent/session_surface.py` | Surface projection: ordered nodes, generation tracking |
| `agent/context_spec.py` | ContextSpec — path through log tree, reconstruct() |
| `agent/parent_context.py` | ParentFork, build_fork_context_v2() |
| `agent/inherited_registry.py` | InheritedSchemaTool — access control wrapper |
| `agent/subagent_tools.py` | Tool discovery, registry building |
| `tools/compact/_tail_boundary.py` | compute_tail_boundary() — middle/tail split |
