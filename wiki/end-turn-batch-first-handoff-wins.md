---
title: 'END_TURN tool batches: the first handoff wins, later calls are skipped'
description: 'When one response batches several calls with an END_TURN (write_handoff), the first END_TURN ends the turn; later calls get a [skipped] result without running.'
tags: [END_TURN, write_handoff, dispatch_tool_calls, _tool_dispatch, SOLO_TOOLS, ask_user, handle_end_turn, merge]
updated: 2026-10-05
---
**Decision (2026-10-05, merge commit 16ed8c4e):** in `agent/_tool_dispatch.py::dispatch_tool_calls`,
the first call that returns `SideEffect.END_TURN` is bookkept in place and becomes the turn's
answer. Every later call in the batch, whether a second handoff or an ordinary tool, is not executed.
It still gets a `[skipped] Not executed: the turn already ended via call <id> ...` result, so
every logged tool/call keeps its tool/result.

**Rejected alternative:** local commit 0f93469c ran every call and let the *last* handoff win.
Both sides fixed review item R2 independently, and their tests contradicted each other. First-wins
(origin 5b3fbc60) was kept because tools requested after the turn has ended would run side
effects that nobody sees afterwards.

**Layered on top:** the `SOLO_TOOLS` gate (`ask_user`, d1f50347). A batch that mixes `ask_user`
with other calls runs nothing at all, so it can never reach an END_TURN. Check order in the loop:
already-ended → pause → solo.

Tests: `tests/test_end_turn_batch.py`, `tests/test_agent_loop.py::TestBatchedHandoffPairing`.

**Env gotcha seen during the merge:** the `dagi` conda env is at
`C:\Users\alexr\miniconda3\envs\dagi`. CLAUDE.local.md's `anaconda3` path does not exist.
