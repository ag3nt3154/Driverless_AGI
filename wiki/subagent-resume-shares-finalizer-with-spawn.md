---
title: 'Resumed subagents go through the same finalizer as immediate ones'
description: 'Timed-out children keep identity by PID; _finalize applies branch_id and stale-generation rejection on both run and resume paths.'
tags: [subagent_api, resume_subagent_by_pid, _finalize, _PendingChild, stale, parent_surface_generation, extend_subagent_timeout, R8]
updated: 2026-10-05
---
Decision/fix 2026-10-05 (Codex review R8), `tools/subagent_api.py`.

## Problem
Only `run_subagent`'s immediate return checked `parent_surface_generation`. After a timeout,
`resume_subagent_by_pid` rebuilt the result from the PID alone, so an inherited child forked
from an outdated parent context came back `ok` and lost its `branch_id`.

## Decision
- `_PendingChild` (handoff_path, branch_id, fork, parent_context) is stored in
  `_pending_children[pid]` on **every** timeout, inherited or not, so a reused PID overwrites
  a dead child's entry rather than inheriting its identity.
- `_finalize(result, child)` is the single place that attaches `branch_id` and turns an
  ok/ok_unverified result into `stale` (with a "generation X -> Y" message). Any new
  completion path must call it.
- Resume keeps the entry while the status is `timeout` and pops it on any terminal status.
- `extend_subagent_timeout` now forwards `message`/`exit_code`/`output_tail`.

Rejected: passing generation metadata through the private runner's `_SubagentState`, which
would leak parent-context concepts into the subprocess layer.

## Residual
Entries for children that are never resumed, or force-killed on pause, remain until PID reuse
or process exit. They belong in the planned owned-run handle (R7/S1).
