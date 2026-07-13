# Windows Notifications for DAGI TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fire a native Windows toast notification from DAGI's TUI (`tui.py`) at three points: DAGI asks a question, DAGI presents a plan for interactive review, and DAGI reaches end-of-response — without ever crashing or blocking the TUI if the notification subsystem is unavailable.

**Architecture:** Add a new best-effort `notify(title, message)` wrapper in `tui/notifications.py` that lazily imports `win11toast` and swallows all exceptions. Add a new `on_plan_shown` no-op-by-default callback to `AgentCallbacks` (agent/loop.py), fired by `ShowPlanTool.run()` (tools/show_plan.py) only in interactive mode. Wire `notify()` into three closures inside `tui/callbacks.py::build_callbacks()`: `on_ask_user`, the new `on_plan_shown`, and `on_done`. No other entry point (`cli.py`, `tg/callbacks.py`, subagents, scheduler) is touched.

**Tech Stack:** Python, `win11toast` (new PyPI dependency, Windows-only toast notifications), `pytest` + `unittest.mock` for tests.

---

### Task 1: `on_plan_shown` callback field on `AgentCallbacks`

**Files:**
- Modify: `C:\Users\alexr\Driverless_AGI\agent\loop.py:207`
- Test: `C:\Users\alexr\Driverless_AGI\tests\test_agent_callbacks.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_callbacks.py`:

```python
"""tests/test_agent_callbacks.py — AgentCallbacks default no-op behavior."""
from __future__ import annotations

from agent.loop import AgentCallbacks


class TestOnPlanShownDefault:
    def test_on_plan_shown_defaults_to_noop(self):
        callbacks = AgentCallbacks()
        # Must not raise, must return None, with zero arguments.
        assert callbacks.on_plan_shown() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi pytest tests/test_agent_callbacks.py -v`
Expected: FAIL with `AttributeError: 'AgentCallbacks' object has no attribute 'on_plan_shown'`

- [ ] **Step 3: Add the field**

In `agent/loop.py`, the `AgentCallbacks` dataclass currently ends with (around line 205-207):

```python
    on_pause:       Callable[[], None] = field(default=lambda: None)
    supports_pause: bool               = False
    # Fired when the harness injects a "continue" prompt because the response had no exit flag.
    # Args: (current_count, max_continuations)
    on_continue_injected: Callable[[int, int], None] = field(default=lambda cur, mx: None)
```

Add a new field immediately after `on_continue_injected`:

```python
    on_pause:       Callable[[], None] = field(default=lambda: None)
    supports_pause: bool               = False
    # Fired when the harness injects a "continue" prompt because the response had no exit flag.
    # Args: (current_count, max_continuations)
    on_continue_injected: Callable[[int, int], None] = field(default=lambda cur, mx: None)
    # Fired when a plan is rendered for interactive review (ShowPlanTool, interactive mode only).
    on_plan_shown: Callable[[], None] = field(default=lambda: None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi pytest tests/test_agent_callbacks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/loop.py tests/test_agent_callbacks.py
git commit -m "feat: add on_plan_shown callback to AgentCallbacks"
```

---

### Task 2: Wire `on_plan_shown` into `ShowPlanTool`

**Files:**
- Modify: `C:\Users\alexr\Driverless_AGI\tools\show_plan.py:42`
- Test: `C:\Users\alexr\Driverless_AGI\tests\test_show_plan.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_show_plan.py`:

```python
"""tests/test_show_plan.py — ShowPlanTool.on_plan_shown wiring."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools.show_plan import ShowPlanTool


@pytest.fixture
def plan_file(tmp_path: Path) -> Path:
    f = tmp_path / "plan.md"
    f.write_text("# Plan: Do the thing\n", encoding="utf-8")
    return f


class TestOnPlanShownWiring:
    def test_interactive_mode_fires_on_plan_shown(self, plan_file: Path):
        callbacks = MagicMock()
        callbacks.on_ask_user.return_value = "ok"
        tool = ShowPlanTool(plan_file=plan_file, callbacks=callbacks, interactive=True)

        tool.run()

        callbacks.on_plan_shown.assert_called_once_with()

    def test_autonomous_mode_does_not_fire_on_plan_shown(self, plan_file: Path):
        callbacks = MagicMock()
        tool = ShowPlanTool(plan_file=plan_file, callbacks=callbacks, interactive=False)

        tool.run()

        callbacks.on_plan_shown.assert_not_called()

    def test_no_callbacks_does_not_raise(self, plan_file: Path):
        tool = ShowPlanTool(plan_file=plan_file, callbacks=None, interactive=True)

        result = tool.run()

        assert "approved by the user" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi pytest tests/test_show_plan.py -v`
Expected: `test_interactive_mode_fires_on_plan_shown` FAILS with `AssertionError: Expected 'on_plan_shown' to have been called once. Called 0 times.` The other two tests pass already (they don't depend on the new behavior).

- [ ] **Step 3: Add the call**

In `tools/show_plan.py`, `ShowPlanTool.run()` currently has:

```python
        if self._callbacks is None:
            return "Plan approved by the user. Call exit_plan_mode, then proceed to Phase 2 execution."

        answer = self._callbacks.on_ask_user("Do you have any modifications?", [], None)
```

Change to:

```python
        if self._callbacks is None:
            return "Plan approved by the user. Call exit_plan_mode, then proceed to Phase 2 execution."

        self._callbacks.on_plan_shown()
        answer = self._callbacks.on_ask_user("Do you have any modifications?", [], None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi pytest tests/test_show_plan.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/show_plan.py tests/test_show_plan.py
git commit -m "feat: fire on_plan_shown when ShowPlanTool renders a plan interactively"
```

---

### Task 3: `tui/notifications.py` — the toast wrapper

**Files:**
- Create: `C:\Users\alexr\Driverless_AGI\tui\notifications.py`
- Test: `C:\Users\alexr\Driverless_AGI\tests\test_tui_notifications.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_notifications.py`:

```python
"""tests/test_tui_notifications.py — notify() best-effort Windows toast wrapper."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from tui.notifications import notify


class TestNotify:
    def test_calls_win11toast_with_title_and_message(self):
        fake_win11toast = MagicMock()
        with patch.dict(sys.modules, {"win11toast": fake_win11toast}):
            notify("DAGI has a question", "What color should the button be?")

        fake_win11toast.notify.assert_called_once_with(
            "DAGI has a question", "What color should the button be?"
        )

    def test_truncates_long_message_to_200_chars(self):
        fake_win11toast = MagicMock()
        long_message = "x" * 500
        with patch.dict(sys.modules, {"win11toast": fake_win11toast}):
            notify("Title", long_message)

        args, _ = fake_win11toast.notify.call_args
        assert len(args[1]) <= 200

    def test_swallows_exception_from_notify_call(self):
        fake_win11toast = MagicMock()
        fake_win11toast.notify.side_effect = RuntimeError("WinRT toast failed")
        with patch.dict(sys.modules, {"win11toast": fake_win11toast}):
            # Must not raise.
            notify("Title", "Message")

    def test_swallows_missing_dependency(self):
        with patch.dict(sys.modules, {"win11toast": None}):
            # sys.modules[name] = None forces `import win11toast` to raise ImportError.
            # Must not raise.
            notify("Title", "Message")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi pytest tests/test_tui_notifications.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tui.notifications'`

- [ ] **Step 3: Write the implementation**

Create `tui/notifications.py`:

```python
"""tui/notifications.py — best-effort native Windows toast notifications.

Fire-and-forget: never raises, never blocks the agent loop. Degrades to a
silent no-op if win11toast is missing, the host isn't Windows, or the
underlying WinRT toast call fails for any reason.
"""
from __future__ import annotations

_MAX_MESSAGE_CHARS = 200


def notify(title: str, message: str) -> None:
    """Best-effort Windows toast. Never raises."""
    try:
        import win11toast

        truncated = message if len(message) <= _MAX_MESSAGE_CHARS else message[:_MAX_MESSAGE_CHARS]
        win11toast.notify(title, truncated)
    except Exception:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi pytest tests/test_tui_notifications.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add tui/notifications.py tests/test_tui_notifications.py
git commit -m "feat: add best-effort Windows toast notification wrapper"
```

---

### Task 4: Add `win11toast` dependency

**Files:**
- Modify: `C:\Users\alexr\Driverless_AGI\requirements.txt:9-10`

- [ ] **Step 1: Install the package in the dev environment**

Run: `conda run -n dagi pip install win11toast`
Expected: successful install output ending in `Successfully installed win11toast-...`

- [ ] **Step 2: Add to requirements.txt**

Current end of the "Core (required)" block in `requirements.txt`:

```
langchain>=1.3.4            # Core LLM orchestration and agent framework
langchain-openai>=1.2.2     # OpenAI provider for LangChain

# ── Optional: Telegram bot ───────────────────────────────────────────────────
```

Insert a new active section between the core block and the Telegram section:

```
langchain>=1.3.4            # Core LLM orchestration and agent framework
langchain-openai>=1.2.2     # OpenAI provider for LangChain

# ── Windows notifications (TUI) ──────────────────────────────────────────────
# Windows-only toast notifications, fired by tui.py at question/plan/done points.
# tui/notifications.py imports this lazily and degrades to a silent no-op on
# non-Windows hosts or if this package is missing — never blocks the TUI.
win11toast>=0.35            # Native Windows 10/11 toast notifications

# ── Optional: Telegram bot ───────────────────────────────────────────────────
```

- [ ] **Step 3: Verify no regression**

Run: `conda run -n dagi pytest tests/test_tui_notifications.py -v`
Expected: PASS (all 4 tests still pass, now with the real package importable)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add win11toast dependency for TUI Windows notifications"
```

---

### Task 5: Wire `notify()` into `tui/callbacks.py`

**Files:**
- Modify: `C:\Users\alexr\Driverless_AGI\tui\callbacks.py`
- Test: `C:\Users\alexr\Driverless_AGI\tests\test_tui_callbacks.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_callbacks.py`:

```python
"""tests/test_tui_callbacks.py — notify() wiring in build_callbacks()."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from tui.callbacks import build_callbacks


def _make_app():
    """MagicMock DagiApp where call_from_thread runs the callable synchronously,
    and _show_ask_user immediately records an answer and sets the event so
    on_ask_user's evt.wait() doesn't hang."""
    app = MagicMock()

    def call_from_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    app.call_from_thread.side_effect = call_from_thread

    def show_ask_user(question, options, timeout, evt, container):
        container.append("ok")
        evt.set()

    app._show_ask_user.side_effect = show_ask_user
    app._stats = MagicMock(input_tok=0, output_tok=0, cost=0.0, thinking_tok=0)
    app._verbose = False
    return app


class TestNotifyWiring:
    def test_on_ask_user_fires_notify(self):
        app = _make_app()
        with patch("tui.callbacks.notify") as mock_notify:
            callbacks = build_callbacks(app, loop_ref=[])
            callbacks.on_ask_user("What color?", [], None)

        mock_notify.assert_any_call("DAGI has a question", "What color?")

    def test_on_plan_shown_fires_notify(self):
        app = _make_app()
        with patch("tui.callbacks.notify") as mock_notify:
            callbacks = build_callbacks(app, loop_ref=[])
            callbacks.on_plan_shown()

        mock_notify.assert_called_once_with(
            "DAGI's plan is ready", "Review the plan and reply with any changes."
        )

    def test_on_done_fires_notify(self):
        app = _make_app()
        with patch("tui.callbacks.notify") as mock_notify:
            callbacks = build_callbacks(app, loop_ref=[])
            callbacks.on_done("All finished.")

        mock_notify.assert_called_once_with("DAGI is done", "All finished.")

    def test_on_done_with_empty_result_uses_fallback_message(self):
        app = _make_app()
        with patch("tui.callbacks.notify") as mock_notify:
            callbacks = build_callbacks(app, loop_ref=[])
            callbacks.on_done("")

        mock_notify.assert_called_once_with("DAGI is done", "Response complete.")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi pytest tests/test_tui_callbacks.py -v`
Expected: FAIL — `test_on_ask_user_fires_notify` and `test_on_done_*` fail with `AssertionError` (notify not called / called with wrong args); `test_on_plan_shown_fires_notify` fails with `AttributeError: 'AgentCallbacks' object has no attribute 'on_plan_shown'` unless Task 1 already landed (it will have, since tasks execute in order) — in that case it fails with `AssertionError: Expected 'notify' to have been called once. Called 0 times.`

- [ ] **Step 3: Wire the three call sites**

In `tui/callbacks.py`, add the import at the top (after the existing `.utils` import):

```python
from .conversation import ConversationPane
from .sidebar import Sidebar
from .utils import _breakdown
from .notifications import notify
```

Change `on_ask_user` (currently starts at line 69) to fire `notify` first:

```python
    def on_ask_user(question, options, timeout):
        notify("DAGI has a question", question)
        evt = threading.Event()
        container: list = []
        app.call_from_thread(app._show_ask_user, question, options, timeout, evt, container)
        safety = (timeout + 60) if timeout is not None else None
        evt.wait(timeout=safety)
        if container:
            return container[0]
        return next((o["label"] for o in options if o.get("recommended")),
                    options[0]["label"] if options else "")
```

Add a new `on_plan_shown` closure right after `on_ask_user` (before `on_continue_injected`):

```python
    def on_plan_shown():
        notify("DAGI's plan is ready", "Review the plan and reply with any changes.")

    def on_continue_injected(cur: int, mx: int) -> None:
```

Add an `on_done` closure right before the final `return AgentCallbacks(...)` (after `on_subagent_event_factory`):

```python
    def on_subagent_event_factory(subagent_type: str) -> Callable[[str], None]:
        return build_subagent_relay_callback(app, subagent_type)

    def on_done(result: str) -> None:
        notify("DAGI is done", result or "Response complete.")

    return AgentCallbacks(
        on_tool_start=on_tool_start, on_tool_end=on_tool_end,
        on_assistant_text=on_assistant_text, on_token_update=on_token_update,
        on_iteration=lambda _: None, on_done=on_done, on_error=on_error,
        on_api_call=on_api_call, on_reasoning=on_reasoning,
        on_compaction=on_compaction, on_model_switch=on_model_switch,
        on_ask_user=on_ask_user, on_emote=on_emote,
        on_subagent_event_factory=on_subagent_event_factory,
        on_pause=on_pause, supports_pause=True,
        on_continue_injected=on_continue_injected,
        on_plan_shown=on_plan_shown,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi pytest tests/test_tui_callbacks.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `conda run -n dagi pytest -v`
Expected: PASS — all previously-passing tests (260+ before this feature) plus the new tests added in Tasks 1, 2, 3, 5 (12 new tests total) pass with zero failures.

- [ ] **Step 6: Commit**

```bash
git add tui/callbacks.py tests/test_tui_callbacks.py
git commit -m "feat: wire Windows toast notifications into TUI ask_user/plan/done callbacks"
```

---

### Task 6: Update documentation

**Files:**
- Modify: `C:\Users\alexr\Driverless_AGI\README.md` (Dependencies section, ~line 717-735)
- Modify: `C:\Users\alexr\Driverless_AGI\TODO.md` (Completed section, top)
- Modify: `C:\Users\alexr\Driverless_AGI\PROJECT_CONTEXT.md` (via `update-project-context` skill)

- [ ] **Step 1: Update README.md Dependencies section**

Read the current "Dependencies" section around line 717-735 (two-tier "Core" / "Additional" format). Add a new subsection after the existing tiers:

```markdown
### Windows notifications (TUI, optional)

- `win11toast` — native Windows 10/11 toast notifications. Installed by default
  via `requirements.txt`. `tui.py` fires a toast when DAGI asks a question,
  presents a plan for review, or reaches end-of-response. Degrades silently
  to a no-op on non-Windows hosts or if the package is missing — never
  blocks the TUI. Not used by `cli.py`, `telegram_bot.py`, subagents, or the
  scheduler.
```

- [ ] **Step 2: Append TODO.md Completed entry**

At the top of the `## Completed` section in `TODO.md`, add:

```markdown
- **Windows toast notifications for TUI** · `done` · `2026-07-13`
  - **Fires at three points:** `ask_user`, interactive `show_plan`, and end-of-response (`on_done`) via `tui/notifications.py::notify()`
  - **New callback:** `AgentCallbacks.on_plan_shown` distinguishes plan review from a generic question
  - **Scope:** `tui.py` only — `cli.py`, `telegram_bot.py`, subagents, and the scheduler are unaffected
  - **Dependency:** `win11toast`, lazily imported and exception-guarded — degrades to silent no-op if missing or non-Windows
```

- [ ] **Step 3: Update PROJECT_CONTEXT.md**

Invoke the `update-project-context` skill to append a new session-log entry documenting this feature (new file `tui/notifications.py`, new `AgentCallbacks.on_plan_shown` field, three new call sites in `tui/callbacks.py`, new `win11toast` dependency).

- [ ] **Step 4: Commit**

```bash
git add README.md TODO.md PROJECT_CONTEXT.md
git commit -m "docs: document TUI Windows notification feature"
```

---

## Self-Review

**Spec coverage** — checked against `docs/superpowers/specs/2026-07-13-windows-notifications-design.md`:
- Three trigger points (question, plan, end-of-response) → Tasks 2, 5. ✓
- Never crash/block if subsystem unavailable → Task 3 (`try/except Exception`, lazy import). ✓
- `tui/notifications.py::notify(title, message)` signature → Task 3. ✓
- New `on_plan_shown` callback, interactive-mode-only → Tasks 1, 2. ✓
- Three wiring call sites in `tui/callbacks.py` only → Task 5. ✓
- `cli.py`/`tg/callbacks.py` untouched → confirmed no task modifies either file. ✓
- Message truncation (~200 chars) → Task 3, `_MAX_MESSAGE_CHARS`. ✓
- `win11toast` as active `requirements.txt` dependency with comment → Task 4. ✓
- Three planned unit test files → Tasks 1 (test_agent_callbacks.py), 2 (test_show_plan.py), 3 (test_tui_notifications.py), 5 (test_tui_callbacks.py). ✓ (spec called for 3 test areas; this plan splits the `on_plan_shown` default-noop check into its own small test file since it's a dataclass-level concern distinct from the tool-level test — no coverage gap, just an extra file.)

**Placeholder scan:** No TBD/TODO/"add error handling"/"similar to Task N" found — every step has complete code.

**Type consistency:** `notify(title: str, message: str) -> None` signature is identical across Task 3's implementation and Task 5's call sites. `on_plan_shown: Callable[[], None]` matches its Task 1 definition, Task 2's invocation (`self._callbacks.on_plan_shown()`), and Task 5's closure/wiring. `AgentCallbacks(...)` constructor call in Task 5 includes every existing keyword argument from the current `tui/callbacks.py` plus the new `on_plan_shown=on_plan_shown` — no accidental drop of an existing wired callback.
