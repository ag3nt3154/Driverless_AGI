# Errors

Navigation to observed issues and verified fixes.

> Last updated: 2026-09-17

## Recent confirmed issues (2026-09)

**PySide GUI — 4 bugs (2026-09-05, all fixed):**
- Right sidebar white on some Windows themes: viewport lacked explicit bg —
  set `viewport().setStyleSheet("background: #1e1e2e")` and give container `right-sidebar`
  object name.
- VAD emotes shown ~1s instead of full GIF loop: expression timer `advance()` at 1s interval
  restarted GIF — skip re-render in `update_expression` while `_movie` is playing.
- Thinking block duplicated in streaming: `_on_assistant_text` reset `_stream_had_content`
  before `_on_reasoning` checked it — stop resetting the flag (let `_on_stream_started` reset it).
- Debug stage-trace lines cluttered conversation — removed `stage_trace` signal and `stage()`
  UI emissions; kept `worker_log` file logging.

**Plan mode removed (2026-09-05):** Plan mode as a system-level feature was retired —
replaced with `/plan` skill + `create_plan` tool. `AgentConfig` fields `plan_mode`,
`plan_file`, `plan_mode_initiated_by`, `previous_branch` removed; `plan_mode_initiated_by`
replaced by `autonomous` bool. `SideEffect.ENTER_PLAN_MODE`/`EXIT_PLAN_MODE` removed.
Registry no longer rebuilds or restricts tools during planning.

**Deliver workflow 7 integration failures (2026-09-05, all fixed):**
(1) `config.yaml` had stale `spawn_*` tool names.
(2) `UpdateTaskStatusTool` captured plan path at construction — now reads
`config.active_plan_file` dynamically.
(3) `check_active_plan` returned plain string on success — now returns
`ToolResult(SET_ACTIVE_PLAN)`.
(4+5) Subagent wrappers discarded error diagnostics — patched.
(6) Deliver skill `ESCALATE` said "enter plan mode" — fixed.
(7) `SetActivePlanTool` containment check didn't call `.resolve()`.

## Open issues

- [Production review (2026-09-15)](../notes/production-review-2026-09-15.md): 19 actionable
  subagent, agent-loop, PySide GUI, and session-persistence findings; all recommendations
  remain unapproved.

- [Broad repository review (2026-09-06)](../notes/broad-review-2026-09-06.md): five P1
  findings (scheduler constructor and timeout, session restore, Telegram final delivery and
  user-answer dispatch) and one P2 finding (CLI project configuration); all unfixed.

**Provider call has no timeout — worker can block for ~30 min** · `open` · found 2026-08-26:
`AgentLoop` builds `openai.OpenAI(api_key=…, base_url=…)` with no `timeout`, so a stalled
provider response falls back to SDK default (600s read, `max_retries=2`). Fix: config-backed
`request_timeout` passed to the client.

**`pyside_gui/app.py` file cap is stale** · `open` · found 2026-08-26:
`test_pyside_app_stays_under_file_cap` asserts ≤500 lines; the file has been 547+ on `main`
since the left-sidebar work. Raise the cap or split the module.

**Two pre-existing `test_agent_loop.py` failures** · `open` · found 2026-09-17:
Isolated while investigating an apparent test hang (see environment issue below).
Both fail on a clean run (`python -u -m pytest tests/test_agent_loop.py -v --timeout=15
--timeout-method=thread`, dagi env python directly) — unrelated to the same-day wiki-index
change (`agent/_loop_helpers.py`), which neither test touches.
1. `TestDispatchToolCallsExtraction::test_deferred_system_messages_land_after_all_tool_results`
   — `roles.index("system", 1)` raises `ValueError`; the deferred system notification is not
   landing after both tool results as expected.
2. `TestProcessLifecycle::test_pause_during_tool_suppresses_post_tool_thinking` — after
   `thread.join(timeout=2.0)`, `thread.is_alive()` is still `True`; looks like a genuine race
   in pause/resume rather than a flaky timing assumption. Not yet root-caused.

## Known environment issues

**`conda run` swallows pytest output until the process exits** · found 2026-09-17:
`conda run -n dagi python -m pytest ...` fully buffers stdout whenever it isn't attached to a
TTY — piping to `tail` or redirecting to a file both look identical to a hang, sometimes for
10+ minutes, even though the suite itself finishes in seconds. Not `conda run`'s own overhead;
its child process's stdout buffering policy switches from line-buffered to fully-buffered once
detached from a terminal, and `conda run` doesn't flush early.
Workaround: call the env's interpreter directly (`<conda root>/envs/dagi/python.exe -u -m
pytest ...`), bypassing the `conda run` wrapper, and pass `-u` for unbuffered output so
progress streams live.

**pytest-qt DLL failure without full conda activation** · found 2026-09-05:
Symptom: `ImportError: DLL load failed while importing QtCore: The specified procedure could
not be found` when running tests without activating the conda environment.
Cause: `PySide6.QtCore` depends on DLLs in the conda env's PATH, not just the PySide6
package directory. `add_dll_directory` does not resolve this.
Workaround: Run with full conda activation, OR use `-p "no:pytest-qt"` to disable the plugin
(entry point name: `pytest-qt`). The `tests/conftest.py` RAM watchdog also conflicts with
`--noconftest`; use both flags for isolated non-Qt tests.

**DeepSeek cache hits plateau** · `fixed` · 2026-08-26:
The ephemeral Session Context board broke the growing request prefix. Board removed entirely;
`dynamic_context.py` deleted; `_board`/`_refresh_dynamic_context`/`_build_dynamic_context`
stripped from `AgentLoop`.

**Typed turn termination** · `fixed` · 2026-08-30:
`main_system.md` required `<<END_OF_RESPONSE>>`, causing corrective continuation after every
text-only reply. Fix: `write_handoff` is the prompt's sole final action; regression-tested.

[Project wiki](../index.md)
