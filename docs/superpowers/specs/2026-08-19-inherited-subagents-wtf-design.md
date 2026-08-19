# Inherited Subagents and `/wtf` — Design Spec

> 2026-08-19

## Problem

DAGI's typed subagents currently start with a fresh system prompt and task envelope. They do not
inherit the parent conversation, so their first provider request cannot reuse the parent's warm
prompt prefix and the model must work from a lossy restatement of relevant context.

The existing compact subprocess already proves that a branch can inherit a versioned snapshot of
the parent's model, messages, tool schemas, and prompt-affecting request settings. That path is
compact-specific: it permits no tool execution and makes one provider call. General subagents need
the same inherited prefix while retaining multi-step tool use and preset-specific access control.

Users also need a TUI command for diagnosing DAGI when it has made an error or is following an
unwanted path. `/wtf` must inspect the same context the parent saw, save a durable error report,
and return only a report reference to the parent context rather than injecting the full diagnosis.

## Goals

- Make inherited parent context the default for every subagent spawned from a live `AgentLoop`.
- Preserve the parent's model, system message, messages, tool schemas, tool order, and
  prompt-affecting request settings through the fork point.
- Append the subagent preset, task, allowed-tool list, and output contract as the first
  provider-visible difference after the inherited prefix.
- Preserve the inherited tool schemas while enforcing the subagent preset's allowlist at dispatch.
- Capture a structured final assistant response and have the subprocess write the handoff file.
- Add TUI-only `/wtf [description]` support for idle and safely paused sessions.
- Save `/wtf` reports under `.dagi/errors/` with `Description`, `Error Report`, and
  `Suggested Fix` sections.
- Return normal subagent handoff content through the parent tool result, as today.
- Return only the `/wtf` invocation and report path to the parent model context.

## Non-goals

- Electron desktop support for `/wtf` in this change.
- Guaranteeing a provider cache hit; routing, expiry, minimum prefix size, and provider behavior
  remain external constraints.
- Allowing a subagent to use a tool absent from the parent request schema.
- Replaying every child event into the parent session log.
- Letting `/wtf` edit code or apply its suggested fix.
- Changing the parent response or tool-result format for ordinary subagents.
- Making standalone `run_subagent()` calls inherit context when no live parent provider exists.

## Core invariants

1. **Stable fork.** A child never inherits a half-recorded assistant/tool exchange.
2. **Exact shared prefix.** The child's inherited request identity matches the parent's request
   snapshot and reconstructed surface through the logical fork.
3. **Child-only instruction.** Preset rules, task text, allowlist, and output contract appear only
   in the appended child task message.
4. **Schema identity.** The first child request retains every inherited tool schema in the same
   order and adds no child-only tool schema.
5. **Dispatch enforcement.** A prompt allowlist is explanatory; the child dispatcher is
   authoritative and returns an error for every disallowed tool call.
6. **No model-written handoff tool.** The subprocess validates final assistant text and writes the
   handoff itself, so `write_handoff` is not added to the request schema.
7. **Append-only provenance.** A parent `BRANCH_START` records the fork; child events remain in the
   child log and existing parent events are never rewritten.
8. **Return isolation.** Ordinary subagents return handoff content. `/wtf` returns only its command
   record and report path; its report body never enters the parent model surface.
9. **Atomic acceptance.** A stale or invalid child result cannot append a successful parent
   reference.

## Terminology

- **Parent context provider:** A loop-owned interface that captures a stable, reconstructable fork
  plus the triggering request snapshot.
- **Inherited prefix:** Parent model identity, request settings, system message, messages, and tool
  schemas through the fork point.
- **Child task:** The first new user message after the inherited prefix. It contains the preset,
  concrete task, access policy, and output contract.
- **Inherited schema registry:** A child dispatcher whose provider-facing schemas exactly match the
  parent while runtime calls delegate only to allowed child tools.
- **Command reference:** The minimal model-visible parent message recording `/wtf` and its report
  path after a successful diagnosis.

## Architecture

### 1. Capture a live parent fork

`AgentLoop` owns a context-provider method and passes it through tool registration into every typed
subagent wrapper and any loop-owned helper that spawns a subagent. `run_subagent()` requests a fork
from that provider after generating the child branch id.

For a normal model-spawned subagent, the inherited prefix is the exact parent request that produced
the assistant's spawn call. It excludes that later assistant response and all of its unresolved
tool calls. This keeps the child request provider-valid even when the assistant emitted multiple
tool calls: the child task can follow the inherited prefix directly instead of appearing between an
assistant tool call and its required tool result. The child task already contains the spawn call's
task arguments. `BRANCH_START` records the current turn and step, the logical `parent_cut_seq`, and
`parent_surface_generation` for provenance, while the frozen request snapshot supplies the exact
provider prefix.

For an idle `/wtf`, the fork ends at the last completed main turn. For paused `/wtf`, the TUI first
waits for a loop checkpoint proving that in-flight response and tool bookkeeping has finished and
the loop is blocked before its next provider request. The cutoff is the last completed step; an
empty newly opened step is not part of the inherited surface.

The provider uses the immutable last-request snapshot as the cache-identical base for an ordinary
spawn. For idle or paused `/wtf`, it reconstructs the stable current surface through
`spec_for_branch()` and `reconstruct()`, using the snapshot for model, header, tool, and provider
identity. Captured credentials are excluded; the child resolves credentials from normal
configuration and environment sources.

If no live context provider exists, `run_subagent()` retains the fresh-subagent path for standalone
scripts and backward compatibility. Every subagent launched from a live parent loop uses the
inherited path by default.

### 2. Generalize the fork-context contract

The versioned fork-context document expands from compact-only request inheritance to a general
child contract. It contains:

```json
{
  "version": 2,
  "branch": {
    "id": "explore_files_ab12cd34",
    "parent_cut_seq": 123,
    "parent_surface_generation": 4
  },
  "request": {
    "model": "provider/model-id",
    "base_url": "https://provider.example/v1",
    "messages": [],
    "tools": [],
    "parallel_tool_calls": false,
    "extra_body": {}
  },
  "child": {
    "type": "explore_files",
    "allowed_tools": ["read", "grep", "find", "bash"]
  }
}
```

The task file remains separate and contains the resolved preset prompt, task envelope, explicit
allowed-tool list, blocked-tool behavior, and required final-response format. Secrets never enter
either file. Temporary fork and task files follow the existing terminal, timeout, resume, and
forced-kill lifecycle.

Version 1 compact contexts remain readable during migration. New general inherited contexts use
version 2. Compact remains a specialized consumer and may migrate to version 2 only where doing so
does not change its validated single-call behavior.

### 3. Construct the child request

The inherited child uses the parent's current model rather than the preset's `model_tier`. A
different model would not share the same provider cache identity. `model_tier` continues to apply
to fresh standalone subagents that lack a parent context provider.

The subprocess starts from the inherited system message and conversation. It appends exactly one
child task user message containing:

```text
## Subagent role
[resolved preset prompt]

## Task
[task envelope]

## Tool access
You may call only: read, grep, find, bash.
Any other inherited tool will return an access-blocked error.

## Final response
[resolved handoff specification]
Return the complete handoff as your final assistant response.
```

The first child's provider-visible difference is this message. No replacement system prompt,
extra tool schema, or parent-visible message is inserted before it.

### 4. Preserve schemas and enforce access

Provider cache identity requires the child to send the inherited parent tool schemas in the same
order. The child therefore builds an inherited-schema registry rather than filtering schemas out.

For each inherited schema, a schema-bound adapter retains the exact serialized schema. If its name
is allowed and the subagent registry can construct a real implementation, dispatch delegates to
that implementation. Otherwise dispatch returns:

```text
Error: Access blocked for tool '<name>' in subagent '<type>'. Allowed tools: ...
```

The result is appended only to the child branch, allowing the child to recover and continue. A
tool named in the preset but absent from the inherited parent schema is unavailable; DAGI reports
that mismatch in the child task and logs rather than adding a schema and breaking the prefix.

This mechanism enforces access in code. Prompt text communicates the policy but is not trusted as
the security boundary.

### 5. Capture and validate handoffs

Inherited subagents do not receive `write_handoff`. They finish by returning the complete handoff
as final assistant text. The subprocess runner captures the successful `AgentLoop.run()` result,
validates it against the preset output contract, creates the target directory, and writes the
file. The existing `SubagentResult` remains the public return type.

Ordinary typed subagents keep their current parent behavior: their wrappers read the validated
handoff and return its content through the original tool result. Thus the parent sees the spawn
tool call followed by the complete handoff result.

Malformed, empty, or truncated final responses receive one corrective child turn describing the
validation error. A second invalid response fails the child. It is not promoted as a verified
handoff and is not returned as successful content.

### 6. Add the `wtf` preset and TUI command

The project adds `.dagi/subagents/wtf/` with a diagnostic prompt, read-only allowlist
(`read`, `grep`, `find`), and a strict output contract:

```markdown
## Description

[concise statement of the error or unwanted behavior]

## Error Report

[evidence, expected versus actual behavior, and root-cause analysis]

## Suggested Fix

[specific remediation; do not apply it]
```

`/wtf` accepts an optional description:

- Bare `/wtf` instructs the child to infer the error or unwanted behavior from inherited context.
- `/wtf <description>` preserves the description verbatim as a diagnostic hint and asks the child
  to use it to pin down the problem.

The TUI intercepts `/wtf` before its existing paused-message injection path. The command requires
an active conversation and runs asynchronously. An idle session remains idle. A paused session
remains paused before, during, and after diagnosis.

The report path is `.dagi/errors/wtf_<id>.md`. On success the TUI parses and displays only the
`Description` section plus the path. The full report stays on disk.

After validation, `AgentLoop` appends one model-visible command reference containing the literal
invocation and normalized project-relative report path. Existing parent message dictionaries stay
byte-identical; this new reference is the only deliberate surface addition. The report body is
never injected. A later user request can ask the parent model to read or edit the referenced file.

### 7. Preserve parent and child provenance

The parent append-only log records `BRANCH_START` for every inherited subagent. It does not ingest
the child's internal model or tool events; those remain in the child session log referenced by
`SubagentResult.session_log_path` when available.

For ordinary subagents, the existing main-branch tool result records handoff content. For `/wtf`,
the command reference records the report path and branch id without pretending that the assistant
initiated the user command. Branch metadata remains non-surface.

Before accepting a child result, the caller verifies the recorded parent surface generation. A
generation mismatch marks the result stale. The handoff may remain on disk for forensics, but no
successful parent result or `/wtf` command reference is appended from it.

## Failure handling

| Failure | Behavior |
| --- | --- |
| No active TUI conversation | Display `Nothing to diagnose`; do not spawn. |
| Paused loop never reaches a safe checkpoint | Time out with an actionable TUI error. |
| Parent fork cannot be reconstructed | Fail before inference; parent surface unchanged. |
| Context version or required field invalid | Fail child startup; preserve logs. |
| Child credentials/model do not match inherited request | Fail before provider call. |
| Preset tool absent from parent schema | Mark unavailable; do not alter schemas. |
| Child calls a disallowed tool | Return access-blocked child tool result and continue. |
| Transient provider error | Apply existing bounded retry policy, then fail. |
| Empty, truncated, or malformed final report | Correct once, then fail unverified. |
| Child timeout | Preserve resumable state; append no success result yet. |
| Parent surface generation changed | Reject as stale; append no success reference. |
| `/wtf` report write fails | Display error; append no command reference. |

Failed branch metadata and child logs remain available for audit. No failure rewrites or removes
existing parent messages.

## Files affected

- `agent/loop.py` — context provider, stable pause checkpoint, fork capture, `/wtf` acceptance.
- `agent/tools.py` — thread the parent context provider into loop-owned subagent spawners.
- `agent/subagent_tools.py` — discovery wiring and inherited-schema registry construction.
- `agent/registry.py` — schema-bound delegated/blocked dispatch support if kept generic.
- `tools/subagent_api.py` — version-2 fork contract, inherited default, configurable handoff dir.
- `tools/_subagent_runner.py` — fork-context lifecycle and existing resume/cleanup integration.
- `tools/subagent_main.py` — general inherited multi-step mode and final-response handoff writing.
- `.dagi/subagents/*/main.py` — store and forward the parent context provider.
- `.dagi/subagents/wtf/prompt.md` — diagnostic behavior.
- `.dagi/subagents/wtf/subagent_config.yaml` — read-only tools and three-section contract.
- `tui/commands.py` — parse, schedule, and render `/wtf`.
- `tui/app.py` — intercept paused `/wtf` before normal injected resume handling.
- `tui/utils.py` — slash help entry.
- Relevant tests under `tests/` for context, runner, main, registry, loop, and TUI behavior.

The implementation may extract fork orchestration from `agent/loop.py` if required to avoid
increasing its existing size and complexity debt. Such extraction must remain behavior-focused;
unrelated loop refactoring is out of scope.

## Test requirements

### Inherited request identity

- A typed subagent's first request uses the parent model and exact inherited system message,
  message dictionaries, tool schemas, tool order, parallel-call setting, and extra body.
- The child task is the first provider-visible difference after the parent prefix.
- The assistant spawn response and all unresolved sibling tool calls are excluded; their triggering
  parent request is the complete inherited prefix.
- Prior compaction replacements are honored and shadowed events are absent.
- Standalone calls without a parent provider retain fresh-subagent behavior.

### Tool access

- Provider-visible schemas remain byte-for-byte equal to the inherited snapshot.
- Allowed tools delegate to real implementations.
- Disallowed tools return the documented error and can be followed by another child step.
- A preset tool absent from the parent schema is not added.
- `write_handoff` is absent unless it already existed in the parent schema, and remains blocked
  unless explicitly allowed.

### Handoff behavior

- Valid final assistant text is written as the verified handoff.
- Ordinary typed wrappers still return full handoff content to the parent tool result.
- Empty, truncated, malformed, and twice-invalid responses fail without verified content.
- Temporary context/task files are cleaned on terminal paths and retained only where resume needs
  them.

### `/wtf`

- Bare `/wtf` requests inference from inherited context.
- Optional description text is preserved verbatim in the child task.
- Reports use `.dagi/errors/wtf_<id>.md` and contain all three required sections.
- The TUI displays only `Description` and path.
- The parent surface receives only the literal invocation and report path, never report content.
- Pre-existing parent message objects remain byte-identical.
- Idle execution stays idle; paused execution waits for a safe checkpoint and stays paused.
- No active conversation, timeout, malformed report, write failure, and stale generation append no
  success command reference.

### Regression and safety

- Compact's inherited single-call behavior remains unchanged.
- Existing subagent timeout, resume, escalation, and status rendering continue to work.
- Tests mock provider calls; no test invokes a real model or the default agent benchmark solver.

## Acceptance criteria

1. Every typed subagent spawned from a live parent loop receives its reconstructed parent context
   and uses the parent's current model and provider request identity.
2. Its first request preserves the parent tool schemas exactly and enforces its preset allowlist
   at dispatch without adding schemas.
3. The child task is the first difference after the inherited prefix.
4. The subprocess writes a validated final assistant response as the handoff without
   `write_handoff` injection.
5. Ordinary subagents still return full handoff content through their parent tool results.
6. TUI `/wtf [description]` works from idle and paused sessions and writes a valid report under
   `.dagi/errors/`.
7. `/wtf` displays only `Description` and path, and appends only the invocation/path reference to
   parent model context.
8. Existing parent messages are never rewritten, and stale or failed results append no success
   reference.
9. Compact and standalone fresh-subagent paths remain backward compatible.
10. Automated tests prove request identity, access enforcement, handoff validation, paused safety,
    return isolation, and failure atomicity without real model usage.
