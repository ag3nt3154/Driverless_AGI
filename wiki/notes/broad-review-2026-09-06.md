# Broad repository review

> Review completed: 2026-09-06. Six actionable findings remain unfixed.

The user explicitly requested a whole-repository broad scan. The reviewed checkout was clean
`main` at `707b573`. Source inspection covered shared runtime/session/tools, scheduler,
Telegram, TUI/PySide, and CLI/config wiring. This was broad sampling, not an exhaustive audit.
No application code edits, commits, live provider calls, or external messaging occurred.
The changes below are proposed remedies, not approved or implemented fixes.

## Open findings

### P1: Scheduler cannot construct its agent loop

`scheduler/runner.py:98` passes `tracker=` to `AgentLoop`, whose parameter is `_tracker`.
An isolated run with the real constructor and mocked config/tracker reproduced
`TypeError: unexpected keyword argument 'tracker'`. Construction is outside the config
exception handler, so the scheduler aborts on its first due task without recording run failure.
Proposed remedy: correct constructor wiring and ensure initialization failures are recorded.

### P1: Session restore loads the first turn snapshot

`agent/history.py:76` chooses the first `session_end`. TUI and PySide reuse the tracker and
finish after every turn (`tui/app.py:_agent_work`, `pyside_gui/app.py:_agent_work`).
A real `SessionTracker` with two finish snapshots followed by `load_raw_messages` restored
only the first turn, losing later context. Proposed remedy: select the latest valid snapshot.

### P1: Telegram drops final handoff delivery

`tg/callbacks.py:88` discards the handoff in `on_done`; `on_tool_end` at line 84 also ignores it.
`agent/_tool_dispatch.py:handle_end_turn` sends the final through `on_done`, not
`on_assistant_text`. Calling the real handler with Telegram callbacks and mocked bookkeeping
returned `FINAL REPORT` while `bot.send_message` was called zero times.
Proposed remedy: wire final delivery while avoiding duplicate text.

### P1: Telegram cannot dispatch answers while a task awaits user input

`tg/bot.py:58,64,143` uses the default sequential application update processor and a blocking
handler that awaits the entire agent task. Installed SDK introspection verified
`max_concurrent_updates=1` and `MessageHandler.block=True` by default. An incoming answer
cannot dispatch while the worker waits on `tg/callbacks.py:66`'s `ask_user` callback;
the timeout falls back, and the queued answer may then become a new task.
Proposed remedy: background task dispatch or deliberate concurrency with per-session guards.
No live Telegram calls were used to verify this finding.

### P1: Scheduler timeout leaves its worker running

`scheduler/runner.py:111-115` uses `thread.join` with a timeout, which does not terminate
the worker. `loop.finish` can run while the worker remains alive, and the scheduler may start
the next task. An independent mocked-loop reproduction with an event-controlled worker
showed timeout recorded and finish called while the worker was still running.
This is latent behind the constructor bug. Proposed remedy: isolated cancellable execution
(for example, a process) or verified cancellation before finalization and the next task.

### P2: CLI omits project configuration during model resolution

`main.py:30-31` calls `resolve_model_config` without `project_path`, then assigns
`config.project_path` afterward. `agent/config_loader.py` merges project overrides only when
the project path is supplied, so CLI ignores project-local model/tools/settings for both
`--project` and the current directory. A mocked CLI invocation with `--project` verified
the resolver received `model_id=None` with no project path.
Proposed remedy: resolve the project before config loading and pass it to the resolver.

## Verification and limits

- Conda `dagi` Python ran `pytest tests --noconftest -p no:pytest-qt` with a fresh writable
  `--basetemp`: 1043 passed, two Windows process-termination tests failed under the sandbox,
  and five warnings were reported.
- The entire `tests/test_bash_tools.py` was rerun outside the sandbox: six passed in 1.32s.
  This identified those failures as sandbox-only; they were not reported as application defects.
- The PySide GUI suite attempt failed before collection with a QtCore DLL load error even
  via `conda run`; GUI behavior was not runtime-verified. This observation does not establish
  whether full environment activation would resolve it.
- The initial pytest attempt encountered a temp-directory permission denial; a writable
  `--basetemp` resolved that obstacle.
- The review is complete; implementation and verification of the proposed remedies remain open.

[Notes](index.md) | [Errors](../errors/index.md) | [Project wiki](../index.md)
