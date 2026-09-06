# Errors

Navigation to observed issues and verified fixes.

> Last updated: 2026-09-06

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

## Known environment issues

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
