# Esc force-kills the active bash process — Design

## Problem

`Esc` in the TUI currently only sets `AgentLoop._pause_event` (`agent/loop.py:345-353`), which the
main loop checks *between* iterations (`agent/loop.py:387`). It never reaches into an in-flight tool
call. A hung or long-running `bash` command — in the main agent loop or inside a worker/review
subagent — cannot be interrupted; the user has to wait out the tool's timeout (`BashTool.DEFAULT_TIMEOUT`
= 120s, or a subagent's own deadline).

## Goal

Pressing `Esc` should, in addition to its existing pause behavior, immediately force-kill whichever
bash process is currently running — whether that's the main agent loop's own `bash` tool call, or a
bash command running inside an active worker/review subagent's own subprocess.

## Scope

Both of the following are in scope:
- The main agent loop's own `BashTool` invocation.
- A bash command running inside an active worker/review subagent (a separate
  `python -m tools.subagent_main` OS process).

Because the main agent loop blocks synchronously on `run_subagent()` while a subagent is in flight
(the architecture only ever runs one subagent at a time, polled from the same worker thread that
would otherwise be executing the main loop's own `bash` tool), at most one of "main-loop bash" or
"subagent" is ever active when `Esc` is pressed. `Esc` does not need to disambiguate between them —
it attempts both kills unconditionally; whichever one has nothing active is a no-op.

## Architecture

### `tools/bash.py` — `BashTool` gains a killable handle

- `BashTool.__init__` adds `self._lock = threading.Lock()`, `self._proc: subprocess.Popen | None = None`,
  `self._killed_by_user = False`.
- `BashTool.run()` stores the `Popen` handle in `self._proc` (under the lock) immediately after
  spawning it, and clears it (under the lock, in a `finally`) before returning.
- New method `force_kill(self) -> bool`:
  - Under the lock, reads `self._proc`. If `None`, returns `False` (nothing to kill).
  - Otherwise sets `self._killed_by_user = True`, releases the lock, and calls the existing
    `self._kill_tree(proc)` (unchanged — `taskkill /F /T /PID` on Windows, `os.killpg(SIGKILL)` on
    POSIX). Returns `True`.
- `run()`'s `communicate()` call, previously blocked, returns normally (not `TimeoutExpired`) once the
  process is killed. After `communicate()` returns, `run()` checks `self._killed_by_user`: if set, it
  returns `f"{output}\n[killed by user]"` (or just `"[killed by user]"` if there was no output) instead
  of the normal exit-code-annotated result.
- No change to the existing timeout-kill path (`except subprocess.TimeoutExpired`) — `force_kill()` is
  a distinct, externally-triggered path that races with it but converges on the same `_kill_tree()`
  call; whichever fires first, the outcome is a killed process tree either way.

### `tools/_subagent_runner.py` — kill all active subagents

- New function `force_kill_active_subagents() -> int`:
  - Under `_active_lock`, takes a snapshot list of `_active.values()` (does not mutate `_active` here —
    `_poll_until()`'s own exit-detection path already pops the entry once it observes the process is
    gone).
  - For each `_SubagentState`, force-kills `state.proc` using the same tree-kill approach as
    `BashTool._kill_tree` (`taskkill /F /T /PID` on Windows, `os.killpg(SIGKILL)` on POSIX). Extract
    this into a shared helper (see "Shared kill-tree helper" below) rather than duplicating it a third
    time.
  - Returns the number of processes killed (used only for logging/debugging; callers don't need to
    branch on it).
  - Swallows per-process errors (already-exited PID, permission issues) the same way `BashTool._kill_tree`
    does today — best-effort, never raises.

### Shared kill-tree helper

- Extract the existing `BashTool._kill_tree` static method into a small shared utility (e.g.
  `agent/_process_kill.py::kill_process_tree(proc: subprocess.Popen) -> None`) so `tools/bash.py` and
  `tools/_subagent_runner.py` call the same code instead of two copies. `BashTool._kill_tree` becomes a
  thin wrapper (or is removed in favor of direct calls to the shared helper) — no behavior change, pure
  dedup.

### `tui/app.py` — wire into `action_pause()`

- `action_pause()` (bound to `escape`, `tui/app.py:124`) currently: checks the worker is alive, checks
  no pending `ask_user`, checks `_current_loop_ref` is set, then calls `loop.pause()` and updates the
  UI.
- Add, right after the existing early-return guards and before/alongside `loop.pause()`:
  ```python
  bash_tool = loop.registry._tools.get("bash")
  if bash_tool is not None:
      bash_tool.force_kill()
  from tools._subagent_runner import force_kill_active_subagents
  force_kill_active_subagents()
  ```
- `loop.registry` is reassigned wholesale on plan-mode transitions (`_rebuild_for_normal_mode` /
  `_rebuild_for_plan_mode`), never mutated in place, so a plain attribute read from the UI thread is
  safe under CPython's GIL — no additional locking needed at this call site.
- The existing UI feedback (`Sidebar.set_status("paused")`, the `"⏸ Paused"` info line) is unchanged;
  no new UI state is introduced for "killed" vs "paused" — the tool/subagent result text itself
  (`[killed by user]` / the subagent error status) is what tells the story in the conversation pane.

## Data Flow (end to end)

1. User presses `Esc` while the agent is running.
2. `action_pause()` calls `bash_tool.force_kill()` and `force_kill_active_subagents()`, then
   `loop.pause()` (clears `_pause_event`), then updates the sidebar/conversation pane — same as today.
3a. **Main-loop bash case:** the killed `Popen`'s `communicate()` unblocks in the worker thread;
   `BashTool.run()` returns `"<partial output>\n[killed by user]"` as the tool result for that call.
3b. **Subagent case:** the killed subprocess causes `_poll_until()` (blocked in the worker thread) to
   observe `proc.poll() is not None` on its next 2-second tick; since no handoff file was written, it
   returns `{"status": "error", "message": "subagent exited (code <N>) without writing handoff"}` —
   the same shape as any other subagent failure, surfaced to the LLM as a tool error.
4. Either way, the current LLM iteration completes with that tool result appended to the conversation,
   then the main loop hits `_pause_event.wait()` (already cleared in step 2) and blocks — identical to
   today's plain-pause behavior. The user can type a message and press Enter to inject a correction and
   resume, exactly as with a normal pause.

## Error Handling

- `force_kill()` / `force_kill_active_subagents()` are no-ops (return `False` / `0`) when nothing is
  active — checked under the same locks that already guard `BashTool._proc` and `_subagent_runner._active`.
  Pressing `Esc` when idle, or while a non-bash tool is running, behaves exactly as it does today: a
  pure pause, nothing killed.
- Both paths reuse the already-hardened `kill_process_tree()` helper, which already tolerates
  already-exited PIDs and platform kill-command failures (best-effort, never raises) — no new
  Windows-specific failure modes are introduced.
- No change to the existing timeout-kill behavior in either `BashTool` or subagent polling — this
  feature only adds an *earlier*, user-triggered path to the same outcome.

## Testing

- `tests/test_bash_tools.py`: new test spawns a long-running command (e.g. a multi-second `sleep`/
  `timeout`), calls `force_kill()` from a second thread shortly after starting it, and asserts:
  - `run()` returns within a small bound (not waiting for the full sleep duration or the default
    120s timeout).
  - The returned string ends with `[killed by user]`.
  - The underlying process is actually gone (best-effort check, e.g. `psutil` if already a test
    dependency, or platform `tasklist`/`ps` grep — match whatever pattern the existing
    `test_hanging_command_is_bounded_by_default_timeout` test already uses to confirm process death).
- New test for `tools/_subagent_runner.py` (co-locate with existing subagent runner tests, or create
  `tests/test_subagent_runner.py` if none exists): spawn a stub long-running subprocess into `_active`
  directly (bypassing a real subagent to avoid a real LLM call), call `force_kill_active_subagents()`,
  and assert a subsequent `_poll_until()` tick returns the `"error"` status (exited without handoff)
  rather than hanging until the polling deadline.
- No new Textual/TUI-level test — the `action_pause()` addition is a thin 3-line wiring change with no
  new UI state; verified manually via the `verify` skill in the implementation phase (start the TUI,
  run a long bash command, press Esc, confirm it's killed and the loop pauses; repeat with a
  long-running subagent).

## Out of Scope

- No new keybinding — reuses `escape` exactly as today; this is additive behavior on the same key, not
  a new one.
- No change to `BashTool`'s existing timeout-kill path or default timeout value.
- No IPC/control-channel into the subagent subprocess for finer-grained "kill only the bash call, keep
  the subagent alive" behavior — killing the whole subagent process tree is the agreed-upon behavior
  for the subagent case (see Scope above).
- No new UI indicator distinguishing "killed" from "plain paused" beyond the tool-result text itself.
