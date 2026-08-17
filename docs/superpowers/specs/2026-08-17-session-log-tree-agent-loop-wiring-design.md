# Session Log Tree — Agent Loop Wiring

> Spec for wiring the session-log-tree data layer into `AgentLoop` and the
> subagent subprocess runner.  Depends on the data layer built in
> `docs/superpowers/plans/2026-08-17-session-log-tree-and-subagent-context.md`.

## Context

The data layer is complete: `branch/start` event type, `SessionEvent.branch`
field, `SessionLog._branches` tracking, `ContextSpec` + `reconstruct()` for
context reconstruction, and `ToolRegistry.deny()` for dispatch-time access
denial.  None of this is wired into the live agent loop or subagent execution
path yet.

## Goal

When a subagent spawns, the parent's `SessionLog` records a `branch/start`
event at the current turn/step.  The subagent's handoff result flows back as
a normal `tool/result` on the main surface (unchanged from today).  The parent
does **not** need to view or replay the subagent's internal events — only the
handoff text and success/failure status matter for now.

This is the minimal wiring that makes the tree structure observable in the
parent's log, and establishes the coupling points for future in-process
subagent execution (where the subagent writes directly to the parent's log
with `branch=<id>`).

## Approach

### Decision: coupling via constructor threading (Option A)

Subagent tools already receive `config`, `callbacks`, and `tracker` in their
constructor (passed by `_discover_subagent_tools()`).  We add `session_log`
as a fourth parameter following the same pattern.  Each subagent tool stores
it and passes it as `parent_log` to `run_subagent()`.

Why this over loop-level interception or context variables:
- Explicit, traceable, testable.
- Subagent tools that don't pass `parent_log` (user-authored, or opts out)
  still work — `None` means no branch logging.
- No special-casing in `_dispatch_tool_calls`.

### Decision: subprocess model unchanged

The subprocess still runs as an independent `AgentLoop` with its own
`SessionLog`.  The parent does not replay subprocess events.  The handoff text
returns as a `tool/result` on the main surface, exactly as today.  When we
later move to in-process subagents, the subagent will write directly to the
parent's `SessionLog` with `branch=<branch_id>`.

### Decision: no deny() wiring yet

Subagents already use `filter_to()` to restrict their tool set.  Switching to
`deny()` (tools stay in schema, denied at dispatch time for provider KV-cache
preservation) requires sharing the parent's tool schema, which depends on
cache-aware context reconstruction — a separate future piece.

## Sequence

```
Parent AgentLoop (turn=3, step=2)
│
├─ 1. LLM calls explore_files(task="find all API routes")
│
├─ 2. _dispatch_tool_calls → ExploreFilesTool.run()
│     → run_subagent(task=..., parent_log=self._session_log)
│
├─ 3. run_subagent() generates branch_id = "explore_files_abc12345"
│
├─ 4. run_subagent() logs branch/start on parent log:
│     parent_log.append(BRANCH_START, {
│         "branch": "explore_files_abc12345",
│         "parent_branch": "main",
│         "turn": 3,  "step": 2,
│     })
│
├─ 5. Subprocess spawns (unchanged), runs, writes handoff, exits
│
├─ 6. run_subagent() returns SubagentResult (unchanged)
│
├─ 7. Back in _dispatch_tool_calls:
│     handoff text becomes tool/result on the main surface (unchanged)
```

## Changes by file

### `agent/loop.py`

Pass `self.log` as `session_log=` to `create_tool_registry()` in the three
call sites: `__init__`, `_rebuild_for_normal_mode`, `_rebuild_for_plan_mode`.

### `agent/tools.py`

`create_tool_registry()` accepts `session_log` parameter, forwards it to
`_discover_subagent_tools()`.

### `agent/subagent_tools.py`

`_discover_subagent_tools()` accepts `session_log` parameter, passes it to
each discovered subagent tool constructor:

```python
tools_by_name[type_name] = obj(
    config=config,
    callbacks=callbacks,
    tracker=tracker,
    session_log=session_log,   # NEW
)
```

### `tools/subagent_api.py`

`run_subagent()` gains `parent_log: SessionLog | None = None` parameter.
Before spawning:

```python
if parent_log is not None and parent_log.open_turn is not None:
    branch_id = f"{subagent_type}_{subagent_id}"
    parent_log.append(
        sev.BRANCH_START,
        {
            "branch": branch_id,
            "parent_branch": "main",
            "turn": parent_log.open_turn,
            "step": parent_log.open_step,
        },
    )
```

`SubagentResult` gains `branch_id: str | None = None` so callers can
correlate the handoff with the branch event.

### `.dagi/subagents/*/main.py` (×10 built-in types)

Each tool constructor gains `session_log=None` keyword arg and stores it.
Each tool's `run()` method passes `parent_log=self._session_log` to
`run_subagent()`.

Example delta for `explore_files`:

```python
def __init__(self, config, callbacks=None, tracker=None, session_log=None):
    ...
    self._session_log = session_log

def run(self, task, custom_instructions=""):
    ...
    result = _subagent_api.run_subagent(
        ...,
        parent_log=self._session_log,
    )
```

### `tools/read/_read.py`

`ReadTool._read_large_text()` calls `subagent_api.run_subagent()` directly.
It doesn't have access to the session log.  No change needed — `parent_log`
defaults to `None`, so no branch logging.  If we later want branch logging
for read-large-text, we thread `session_log` through `ReadTool`'s constructor.

### Legacy bypass: `tools/explore_files/_explore_files.py`, `tools/web_research/_web_research.py`

These call `_runner.run_subagent()` directly, bypassing `subagent_api`.
They predate the subagent refactor and are superseded by the auto-discovered
versions in `.dagi/subagents/`.  No changes — they won't get branch logging,
which is acceptable since the `.dagi/subagents/` versions are the active path.

## Not in scope

- **Event replay from subprocess into parent log** — deferred until in-process
  subagent execution.
- **Cache-aware context reconstruction** — subagents still build their own
  system prompt and tool schema independently.
- **`ToolRegistry.deny()` wiring** — depends on shared tool schemas.
- **Real-time branch event streaming** — subprocess events stay local.
- **Changes to `_subagent_runner.py` or `subagent_main.py`** — subprocess
  execution path is unchanged.

## Testing

- Unit test: `run_subagent()` with a mock `parent_log` verifies `branch/start`
  is appended with the correct branch_id, turn, and step before the subprocess
  spawns.
- Unit test: `run_subagent()` with `parent_log=None` still works (no branch
  logging, backward compatible).
- Unit test: each subagent tool constructor accepts `session_log` without
  error and stores it.
- Integration test: full parent `AgentLoop.run()` that triggers a subagent
  tool call verifies the parent's `SessionLog` contains a `branch/start`
  event after the tool returns.
- Existing 835 tests must continue passing unchanged.
