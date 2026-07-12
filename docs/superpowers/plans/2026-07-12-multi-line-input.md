# Multi-line Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Shift+Enter submitting instead of inserting a newline, add Ctrl+N / Ctrl+Enter as universal newline bindings, increase default input height, and add a Ctrl+O compose-mode that expands the input to fill the screen.

**Architecture:** All changes live in two files — `tui/prompt_input.py` (key bindings + border title) and `tui/app.py` (CSS height, BINDINGS, compose state, toggle action, auto-collapse on submit). Tests use Textual's `App.run_test()` pilot wrapped in `asyncio.run()` (no pytest-asyncio needed).

**Tech Stack:** Python 3.11+, Textual 8.x, pytest, conda env `dagi`

---

## File Map

| File | Change |
|------|--------|
| `tui/prompt_input.py` | Add `ctrl+n` and `ctrl+enter` newline branches; set `border_title` |
| `tui/app.py` | CSS `height: 5 → 8`; add `BINDINGS` entry; add `_input_expanded`; add `action_toggle_compose()`; collapse on submit |
| `tests/test_prompt_input_multiline.py` | New — Textual pilot tests for newline key bindings |

---

### Task 1: Add ctrl+n and ctrl+enter newline bindings

**Files:**
- Modify: `tui/prompt_input.py`
- Create: `tests/test_prompt_input_multiline.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prompt_input_multiline.py`:

```python
"""tests/test_prompt_input_multiline.py — Textual pilot tests for PromptInput newline bindings."""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from tui.prompt_input import PromptInput


class _App(App[None]):
    """Minimal host app for PromptInput."""
    submitted: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.submitted = []

    def compose(self) -> ComposeResult:
        yield PromptInput(id="prompt")

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        self.submitted.append(event.value)


def test_ctrl_n_inserts_newline_not_submit() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            await pilot.focus("#prompt")
            await pilot.press("ctrl+n")
            widget = app.query_one(PromptInput)
            assert widget.text == "\n"
            assert app.submitted == []

    asyncio.run(run())


def test_ctrl_enter_inserts_newline_not_submit() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            await pilot.focus("#prompt")
            await pilot.press("ctrl+enter")
            widget = app.query_one(PromptInput)
            assert widget.text == "\n"
            assert app.submitted == []

    asyncio.run(run())


def test_shift_enter_inserts_newline_not_submit() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            await pilot.focus("#prompt")
            await pilot.press("shift+enter")
            widget = app.query_one(PromptInput)
            assert widget.text == "\n"
            assert app.submitted == []

    asyncio.run(run())


def test_enter_with_text_submits_and_clears() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            await pilot.focus("#prompt")
            widget = app.query_one(PromptInput)
            widget.load_text("hello")
            await pilot.press("enter")
            assert app.submitted == ["hello"]
            assert widget.text == ""

    asyncio.run(run())


def test_enter_without_text_does_not_submit() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            await pilot.focus("#prompt")
            await pilot.press("enter")
            assert app.submitted == []

    asyncio.run(run())
```

- [ ] **Step 2: Run tests — expect FAIL (ctrl+n and ctrl+enter not yet handled)**

```
& "C:\Users\alexr\miniconda3\Scripts\conda.exe" run -n dagi pytest tests/test_prompt_input_multiline.py -v
```

Expected: `test_ctrl_n_inserts_newline_not_submit` FAIL, `test_ctrl_enter_inserts_newline_not_submit` FAIL; shift+enter and enter tests may pass.

- [ ] **Step 3: Add ctrl+n and ctrl+enter branches to PromptInput**

Open `tui/prompt_input.py`. Replace the existing `on_key` body:

```python
def on_key(self, event: events.Key) -> None:
    if event.key == "enter":
        event.prevent_default()
        event.stop()
        text = self.text
        if text.strip():
            self.post_message(self.Submitted(text))
        self.load_text("")
    elif event.key in ("shift+enter", "ctrl+n", "ctrl+enter"):
        event.prevent_default()
        event.stop()
        self.insert("\n")
```

(The three newline keys are collapsed into one `elif` with an `in` check — no duplication.)

- [ ] **Step 4: Run tests — all should pass**

```
& "C:\Users\alexr\miniconda3\Scripts\conda.exe" run -n dagi pytest tests/test_prompt_input_multiline.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```
git add tui/prompt_input.py tests/test_prompt_input_multiline.py
git commit -m "feat: add ctrl+n / ctrl+enter as universal newline bindings in PromptInput"
```

---

### Task 2: Increase default prompt height and add border hint

**Files:**
- Modify: `tui/app.py`

- [ ] **Step 1: Update CSS height in DagiApp**

In `tui/app.py`, find the `CSS` class variable. Change the `#prompt` rule from `height: 5` to `height: 8`:

```python
CSS = """
Screen           { layout: vertical; }
ConversationPane { height: 1fr; }
Sidebar          { height: 12; border-bottom: solid $panel; }
#running-indicator { height: 1; display: none; color: $success; text-align: center; }
#prompt          { dock: bottom; height: 8; border-top: solid $panel; }
"""
```

- [ ] **Step 2: Set border_title in on_mount**

In `tui/app.py`, inside `on_mount`, add after `self.query_one("#prompt", PromptInput).focus()`:

```python
self.query_one("#prompt", PromptInput).border_title = "ctrl+n = newline · ctrl+o = compose"
```

The full `on_mount` should look like:

```python
def on_mount(self) -> None:
    self._config = resolve_model_config(self._model_id, project_path=self._project_path)
    self._load_maps()
    conv = self.query_one(ConversationPane)
    conv.write(Text(
        f"Driverless AGI  ·  {self._model_name}  ·  {self._project_path}",
        style="bold cyan",
    ))
    conv.write(Text("Type /help for commands · /exit to leave", style="dim"))
    self.query_one("#prompt", PromptInput).focus()
    self.query_one("#prompt", PromptInput).border_title = "ctrl+n = newline · ctrl+o = compose"
    self.set_interval(2.0, self._poll_plan)
    self.set_interval(0.1, self._tick_spinner)
```

- [ ] **Step 3: Run the full test suite to confirm nothing broken**

```
& "C:\Users\alexr\miniconda3\Scripts\conda.exe" run -n dagi pytest tests/ -v
```

Expected: all existing tests pass (these changes don't touch any tested code paths).

- [ ] **Step 4: Commit**

```
git add tui/app.py
git commit -m "feat: increase prompt height to 8 and add newline hint in border title"
```

---

### Task 3: Implement compose mode (ctrl+o)

**Files:**
- Modify: `tui/app.py`

- [ ] **Step 1: Add `_input_expanded` state to `__init__`**

In `tui/app.py`, inside `DagiApp.__init__`, add after the existing instance variable declarations:

```python
self._input_expanded: bool = False
```

The full `__init__` signature block (just the assignments, not the signature):

```python
def __init__(self, model_id: str | None, project: str | None, verbose: bool) -> None:
    super().__init__()
    self._project_path = Path(project).resolve() if project else Path.cwd()
    self._model_id = model_id
    self._verbose = verbose
    self._model_name = get_model_display_name(model_id)
    self._stats = _Stats()
    self._config: AgentConfig | None = None
    self._active_loop: AgentLoop | None = None
    self._worker: threading.Thread | None = None
    self._pending_ask: tuple | None = None
    self._current_loop_ref: list = []
    self._skill_map: dict = {}
    self._workflow_map: dict = {}
    self._spinner_idx: int = 0
    self._input_expanded: bool = False
```

- [ ] **Step 2: Add ctrl+o to BINDINGS**

In `tui/app.py`, replace:

```python
BINDINGS = [("ctrl+c", "quit", "Quit"), ("escape", "pause", "Pause")]
```

with:

```python
BINDINGS = [
    ("ctrl+c", "quit", "Quit"),
    ("escape", "pause", "Pause"),
    ("ctrl+o", "toggle_compose", "Compose"),
]
```

- [ ] **Step 3: Add `action_toggle_compose` method**

Add the following method to `DagiApp`, after `action_pause`:

```python
def action_toggle_compose(self) -> None:
    self._input_expanded = not self._input_expanded
    conv = self.query_one(ConversationPane)
    inp = self.query_one("#prompt", PromptInput)
    conv.display = not self._input_expanded
    inp.styles.height = "1fr" if self._input_expanded else 8
```

- [ ] **Step 4: Auto-collapse on submit when in compose mode**

In `tui/app.py`, inside `on_prompt_input_submitted`, add collapse logic at the very top of the method (before any other logic):

```python
def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
    if self._input_expanded:
        self.action_toggle_compose()
    raw = event.value.strip()
    if not raw:
        return
    # ... rest of existing method unchanged ...
```

The full updated `on_prompt_input_submitted`:

```python
def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
    if self._input_expanded:
        self.action_toggle_compose()
    raw = event.value.strip()
    if not raw:
        return
    if self._pending_ask is not None:
        ask_evt, container, options, _ = self._pending_ask
        self._pending_ask = None
        container.append(raw)
        self.query_one(ConversationPane).write(
            Panel(raw, title="[bold cyan]You[/bold cyan]",
                  title_align="left", border_style="cyan", padding=(0, 1))
        )
        ask_evt.set()
        self.query_one("#prompt", PromptInput).disabled = True
        self._show_running_indicator()
        return
    if (
        self._worker and self._worker.is_alive()
        and self._current_loop_ref
        and not self._current_loop_ref[0]._pause_event.is_set()
    ):
        loop = self._current_loop_ref[0]
        conv = self.query_one(ConversationPane)
        conv.write(Panel(raw, title="[bold cyan]You[/bold cyan]",
                         title_align="left", border_style="cyan", padding=(0, 1)))
        self.query_one("#prompt", PromptInput).disabled = True
        self._show_running_indicator()
        self.query_one(Sidebar).set_status("running")
        loop.inject_and_resume(raw)
        return
    if raw.lower() in ("exit", "quit", "q"):
        self.exit()
        return
    if raw.startswith("/"):
        self._handle_slash(raw)
    else:
        self._dispatch_agent(raw)
```

- [ ] **Step 5: Run the full test suite**

```
& "C:\Users\alexr\miniconda3\Scripts\conda.exe" run -n dagi pytest tests/ -v
```

Expected: all tests pass (compose mode logic touches no unit-tested paths).

- [ ] **Step 6: Manual smoke test**

```
& "C:\Users\alexr\miniconda3\Scripts\conda.exe" run -n dagi python tui.py
```

Verify:
1. Input box is visibly taller (8 lines) with border hint visible
2. `ctrl+n` inserts a newline (cursor moves down, no submission)
3. `ctrl+o` hides the conversation pane and expands input to full height
4. `ctrl+o` again restores conversation pane and collapses input
5. Typing text + Enter in compose mode collapses back to normal, then submits

- [ ] **Step 7: Commit**

```
git add tui/app.py
git commit -m "feat: add ctrl+o compose mode — expands input to full screen, auto-collapses on submit"
```
