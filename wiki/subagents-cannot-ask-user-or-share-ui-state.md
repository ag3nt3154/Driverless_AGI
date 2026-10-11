---
title: 'Subagents run in a separate process: no ask_user, no shared UI state (RPA repair runs in the main agent)'
description: 'Decision 2026-10-12: the planned operator subagent was dropped; rpa_repair/rpa_patch are main-agent tools because subagent processes cannot ask the Admiral or see dagi-opened windows.'
tags: [subagent, subagent_main, ask_user, on_ask_user, rpa, rpa_repair, rpa_patch, operator, _ProcessUiState]
updated: 2026-10-12
---
Decision (Admiral, 2026-10-12, RPA Subtask 17): the repair of a halted workflow runs in the
**main agent**. The planned `operator` subagent was dropped from v1.

Why — a typed subagent is a separate process (`tools/_subagent_runner.py` starts
`tools.subagent_main`):
- Its pipe callbacks (`_build_pipe_callbacks`) have no `on_ask_user`, so every safety gate
  that must ask the Admiral denies (fail-closed), and a patch could never be approved.
- UI state is per process (`tools/ui/_session.py` `_ProcessUiState`): the subagent cannot see
  the windows/tabs the main process opened or adopted from a replay.
- The main process holds dagi's Firefox profile; a second Firefox on it does not start.

Rejected: an ask_user bridge over the subagent pipe plus a separate profile — larger and
riskier; kept as an open follow-up in the RPA plan.

General gotcha: any tool that needs `ask_user`, the GUI, or process-wide state will not work
inside a typed subagent as things stand.
