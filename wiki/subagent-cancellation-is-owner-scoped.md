---
title: 'Subagent cancellation is scoped to the owning AgentLoop'
description: 'interrupt() kills only subagents spawned under the loop''s _owner_id (owner_scope ContextVar); new spawn entry points must be decorated with _owns_subagents.'
tags: [force_kill_active_subagents, owner_scope, _owner_id, _owns_subagents, ContextVar, AgentLoop.interrupt, R20, subagent]
updated: 2026-10-11
---
## Decision (2026-10-11, fix for review finding R20)

`AgentLoop.interrupt()` used to call `force_kill_active_subagents()`, which killed every
subagent in the process-global `_active` table. GUI agents share one process, so ESC on one
agent killed another agent's delegated work.

Now:
- Each `AgentLoop` has `_owner_id = uuid4().hex`. A uuid, not `id(self)`: `id()` values are
  reused after garbage collection.
- `@_owns_subagents` (in `agent/loop.py`) wraps `run()`, `compact()` and `run_wtf()` in
  `tools._subagent_runner.owner_scope(self._owner_id)`.
- `run_subagent` records `_current_owner.get()` on `_SubagentState.owner` at spawn. The
  owner stays the same through timeouts and `resume_subagent`.
- `interrupt()` calls `force_kill_active_subagents(owner=self._owner_id)`. The no-argument
  call keeps the kill-all behaviour, for application shutdown only.

Rejected:
- An explicit `owner=` parameter on every `run_subagent` call site: too many call sites
  (tools, `.dagi/subagents/*/main.py`, compaction, `/wtf`, the reader job).
- Ownership by thread id: `interrupt()` runs on the GUI thread, not the loop thread.

## Gotchas

- **A new `AgentLoop` entry point that can spawn subagents must have `@_owns_subagents`.**
  Without it, its children get owner `None`, and no interrupt ever kills them.
- **A ContextVar does not go to a new thread.** If spawn work moves to a worker or executor
  thread, copy the context (`contextvars.copy_context().run`) or enter `owner_scope` there.
- Residual (R8): after a forced kill, the child's `_pending_children` entry in
  `tools/subagent_api.py` stays until a terminal resume.

Tests: `tests/test_subagent_owner.py` (kill selection only; `kill_process_tree` is mocked).
