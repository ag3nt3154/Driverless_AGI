# Windows Notifications for DAGI TUI — Design

> Date: 2026-07-13

## Problem

When running `tui.py`, the Admiral is frequently alt-tabbed away while DAGI
works. There is currently no way to know DAGI needs attention (a question,
a plan awaiting review) or has finished a response, without keeping the
terminal window in view at all times.

## Goals

- Fire a native Windows toast notification at three points in a TUI session:
  1. DAGI asks a question (`ask_user` tool)
  2. DAGI presents a plan for interactive review (`show_plan` tool, interactive mode only)
  3. DAGI reaches end-of-response (`<<END_OF_RESPONSE>>` / `<<TASK_END>>` / continuation budget exhausted)
- Never crash or block the TUI if the notification subsystem is
  unavailable or fails (missing dependency, non-Windows host, toast API error).

## Non-Goals

- `cli.py` REPL, `telegram_bot.py`, subagents, and `scheduler/runner.py` are
  explicitly out of scope. Telegram already pushes to a phone; subagents and
  the scheduler run headless/autonomously and a desktop toast per subagent
  question would be noisy and generally unwanted.
- No user-facing on/off setting in `config.yaml` for this iteration — YAGNI.
  If it turns out to be noisy, that's a follow-up.
- No toast click-to-focus / action buttons — fire-and-forget only.

## Design

### Notification mechanism — `tui/notifications.py`

```python
def notify(title: str, message: str) -> None:
    """Best-effort Windows toast. Never raises."""
```

- Lazily imports `win11toast` inside the function body and wraps the whole
  thing in `try/except Exception` — mirrors the existing defensive pattern
  used for optional web tools (`ddgs`/`crawl4ai`) and for compaction
  failures (`AgentLoop._compact_context`). A missing dependency, a
  non-Windows host, or any WinRT/toast failure degrades to a silent no-op —
  it must never interrupt the agent loop or crash the TUI.
- Called directly on whatever thread triggers it (the `AgentLoop` worker
  thread) — no `App.call_from_thread()` indirection needed, since this is
  an OS-level call, not a Textual widget mutation.
- Message bodies are truncated (~200 chars) before being passed to the
  toast API to avoid oversized/garbled notifications.

### New callback — `on_plan_shown`

`AgentCallbacks` (agent/loop.py) gains:

```python
on_plan_shown: Callable[[], None] = field(default=lambda: None)
```

`ShowPlanTool.run()` (tools/show_plan.py) calls `self._callbacks.on_plan_shown()`
immediately after rendering the plan via `on_assistant_text`, and only when
`self._interactive` is True (autonomous mode auto-approves — no human is
waiting, so no notification is useful).

Rationale: `ShowPlanTool` already calls `on_ask_user("Do you have any
modifications?", ...)` right after rendering the plan, so in principle
the existing `on_ask_user` hook could distinguish "plan review" from a
regular question by matching that literal string. That's brittle — it
silently breaks if the prompt wording changes — and it's inconsistent with
how DAGI already models distinct lifecycle events via dedicated
single-purpose callbacks (`on_compaction`, `on_model_switch`,
`on_continue_injected`, etc.). A dedicated `on_plan_shown` callback costs
nothing elsewhere (default no-op) and keeps the two notification types
correctly and durably distinguishable.

### Wiring — `tui/callbacks.py`

Three call sites inside `build_callbacks()`:

1. `on_ask_user(question, options, timeout)` — call
   `notify("DAGI has a question", question)` before
   `app.call_from_thread(app._show_ask_user, ...)` / the blocking wait.
2. New `on_plan_shown()` closure — calls
   `notify("DAGI's plan is ready", "Review the plan and reply with any changes.")`.
3. `on_done(result)` — currently `lambda _: None` (a no-op) in the
   `AgentCallbacks(...)` construction at the bottom of `build_callbacks()`.
   Replaced with a real closure that calls
   `notify("DAGI is done", result or "Response complete.")`.

All three are wired only in `tui/callbacks.py::build_callbacks()` — `cli.py`
and `tg/callbacks.py` are untouched, so CLI/Telegram sessions get zero
behavior change and zero new import cost.

### Dependency

`win11toast` added to `requirements.txt` as an active (uncommented)
dependency, since the TUI is the primary Windows workflow and the import
is guarded regardless. A short comment notes it's Windows-only and that
`tui/notifications.py` degrades gracefully without it.

## Testing

- Unit test for `tui/notifications.py::notify()`: mock `win11toast.notify`,
  assert it's called with expected args; assert `notify()` swallows an
  exception raised by the mock without propagating.
- Unit test for `ShowPlanTool`: assert `on_plan_shown` is called in
  interactive mode and NOT called in autonomous mode.
- Unit test for `tui/callbacks.py::build_callbacks()`: assert `on_ask_user`,
  `on_plan_shown`, and `on_done` each invoke `notify` with the expected
  title (mocking `tui.notifications.notify`).

## Open Questions / Follow-ups (not blocking)

- If this proves noisy in practice, a `config.yaml` toggle
  (`notifications_enabled: bool`) would be the natural follow-up.
