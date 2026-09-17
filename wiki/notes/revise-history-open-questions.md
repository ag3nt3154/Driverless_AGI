# /revise-history — Open Questions

> Created: 2026-09-17

## `/hist`-restored sessions

When a session is restored via `/hist`, the `SessionLog` contains seed events
from a previous conversation. It is unresolved whether `/revise-history` should:

- **(a)** Allow revising into the seed (treat restored steps the same as new ones)
- **(b)** Stop at the seed boundary (only steps added in the current session are removable)

This needs a decision before `/revise-history` can be used safely in restored sessions.
For now, the behaviour at the seed boundary is undefined and should be addressed in
a follow-up task.

## Subagent branch interleaving

`SessionLog.revise_last_step()` (added 2026-09-17, `agent/session_log.py`) removes a
step by taking a positional slice of `self._events` between the step's start/end
indices (and the enclosing turn's, if it was the turn's only step). This slice is
**not** branch-filtered: if a subagent was spawned mid-step (`branch/start` + its own
non-"main" events), and those events physically interleave with the main-branch step
being removed, they get deleted too — even though the removal range itself is computed
purely from main-branch turn/step boundaries. `_rebuild_state()` only replays
`branch == "main"` events into derived state, so a deleted subagent branch's
`branch/start` registration would silently disappear from `self._branches` as well.

No test exercises this because it was out of scope for the original `/revise-history`
design interview (which did not consider subagent branches). It should be addressed
in a follow-up task — likely by either (a) preserving non-"main" events that fall
within a removed range, or (b) explicitly deciding that revising a step also revises
any subagent branch it spawned (and documenting that as intended).
