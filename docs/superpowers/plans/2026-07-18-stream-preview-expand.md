# StreamPreview Full-Window Expand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While a response is actively streaming, `StreamPreview` expands to fill the full window (everything except `Sidebar` and the prompt box) instead of being capped at 14 rows / 12 lines, then collapses back to today's behavior when the stream ends.

**Architecture:** `StreamPreview` gains `expand()` (sets `height: 1fr`, clears `max-height`) and an extended `finish()` (restores `height: auto` / `max-height: 14`), plus size-aware tail-line calculation. `DagiApp` gains two orchestration methods that hide/show `ConversationPane` in lockstep with the preview. `tui/callbacks.py` wires the trigger to the *first rendered delta* of a stream segment (not stream-start) to avoid a blank-screen flash on segments with no visible content, and the collapse to `on_stream_end` guarded by a per-segment flag.

**Tech Stack:** Python, Textual (TUI framework), pytest, Textual's async `run_test()` test harness.

**Spec:** [docs/superpowers/specs/2026-07-18-stream-preview-expand-design.md](../specs/2026-07-18-stream-preview-expand-design.md)

---

### Task 1: `StreamPreview.expand()` / extended `finish()`

**Files:**
- Modify: `tui/streaming.py`
- Test: `tests/test_stream_preview.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_stream_preview.py`:

```python
def test_expand_sets_flex_height_and_clears_max_height() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            w.expand()
            assert w._expanded is True
            assert w.styles.height.unit.name == "FRACTION"
            assert w.styles.max_height is None
    asyncio.run(run())


def test_finish_after_expand_restores_collapsed_css() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            w.expand()
            w.finish()
            assert w._expanded is False
            assert w.styles.height.unit.name == "AUTO"
            assert w.styles.max_height.value == 14
    asyncio.run(run())


def test_finish_without_expand_still_resets_defaults() -> None:
    """finish() must be safe to call on a preview that was never expanded
    (the common case: most stream segments never grow past the 14-row cap)."""
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            w.show_progress("", "hi")
            w.finish()
            assert w._expanded is False
            assert w.styles.display == "none"
    asyncio.run(run())


def test_render_tail_uses_widget_height_when_expanded() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test(size=(80, 40)) as pilot:
            w = app.query_one(StreamPreview)
            w.show_progress("", "hi")   # display: block, so layout gives it real size
            w.expand()
            await pilot.pause()
            assert w.size.height > StreamPreview.TAIL_LINES
            long_text = "\n".join(f"line {i}" for i in range(200))
            rendered = str(w._render_tail("", long_text))
            assert len(rendered.splitlines()) == w.size.height
    asyncio.run(run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_stream_preview.py -v`
Expected: the four new tests FAIL — `expand`/`_expanded` don't exist yet (`AttributeError`), and `_render_tail` still ignores widget size.

- [ ] **Step 3: Implement `expand()` and extend `finish()` in `tui/streaming.py`**

Replace the whole file content with:

```python
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class StreamPreview(Static):
    """Live preview of the currently-streaming assistant turn.

    ConversationPane is a RichLog — append-only, so in-flight text cannot be
    updated there without leaving stale partial copies in scrollback. This
    widget shows the growing reasoning/text while a response streams; when the
    stream ends it hides again and the final Markdown/Panel is written to the
    conversation pane exactly as before streaming existed.

    Hidden via DEFAULT_CSS until show_progress() is first called. Only the
    last TAIL_LINES lines are rendered so the preview never crowds out the
    conversation; the full text always lands in the conversation pane at the
    end of the turn.

    While expanded (see expand()), the widget fills the full window instead of
    the 14-row cap, and the visible tail grows to match its actual rendered
    height instead of the fixed TAIL_LINES constant.
    """

    TAIL_LINES = 12

    DEFAULT_CSS = """
    StreamPreview {
        display: none;
        height: auto;
        max-height: 14;
        padding: 0 1;
        border-top: dashed $panel;
        color: $text-muted;
    }
    """

    _expanded: bool = False

    def show_progress(self, reasoning: str, text: str) -> None:
        """Render the accumulated stream so far and make the widget visible."""
        self.styles.display = "block"
        self.update(self._render_tail(reasoning, text))

    def expand(self) -> None:
        """Grow to fill available space instead of the 14-row cap."""
        self._expanded = True
        self.styles.height = "1fr"
        self.styles.max_height = None

    def finish(self) -> None:
        """Hide, clear, and restore the collapsed 14-row/12-line defaults."""
        self.styles.display = "none"
        self.update("")
        self._expanded = False
        self.styles.height = "auto"
        self.styles.max_height = 14

    def _tail_line_count(self) -> int:
        if self._expanded and self.size.height > 0:
            return self.size.height
        return self.TAIL_LINES

    def _render_tail(self, reasoning: str, text: str) -> Text:
        out = Text()
        if reasoning:
            out.append("\U0001f9e0 ", style="dim")
            out.append(reasoning.strip(), style="dim italic")
        if reasoning and text:
            out.append("\n\n")
        if text:
            out.append(text)
        lines = out.split("\n", allow_blank=True)
        limit = self._tail_line_count()
        if len(lines) > limit:
            lines = lines[-limit:]
        return Text("\n").join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_stream_preview.py -v`
Expected: all tests PASS, including the pre-existing `test_render_tail_keeps_only_last_lines` (unaffected — `_expanded` defaults to `False`, so `_tail_line_count()` returns `TAIL_LINES` exactly as before).

- [ ] **Step 5: Commit**

```bash
git add tui/streaming.py tests/test_stream_preview.py
git commit -m "feat(tui): add StreamPreview.expand() and size-aware tail rendering"
```

---

### Task 2: `DagiApp` expand/collapse orchestration methods

**Files:**
- Modify: `tui/app.py`

No new test file for this task — these two methods are pure Textual widget plumbing with no branching logic; they are exercised indirectly by Task 3's callback tests (via a mocked `app`) and are trivial enough that a dedicated unit test would just re-assert the two lines of code. Task 3's tests are the behavioral check that matters (are these methods *called* at the right time).

- [ ] **Step 1: Add the two methods to `DagiApp`**

In `tui/app.py`, add these two methods right after `_hide_running_indicator` (around line 243, before `_enable_input`):

```python
    def _expand_stream_preview(self) -> None:
        self.query_one(ConversationPane).display = False
        self.query_one(StreamPreview).expand()

    def _collapse_stream_preview(self) -> None:
        self.query_one(ConversationPane).display = True
```

`ConversationPane` and `StreamPreview` are already imported at the top of `tui/app.py` (lines 17 and 20) — no new imports needed.

- [ ] **Step 2: Sanity-check the app still boots**

Run: `conda run -n dagi python -m pytest tests/ -k tui -v`
Expected: no failures (this task adds dead code — nothing calls these methods yet, so existing behavior is unchanged).

- [ ] **Step 3: Commit**

```bash
git add tui/app.py
git commit -m "feat(tui): add DagiApp expand/collapse helpers for StreamPreview"
```

---

### Task 3: Wire expand/collapse into `tui/callbacks.py`

**Files:**
- Modify: `tui/callbacks.py`
- Test: `tests/test_tui_callbacks.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_callbacks.py`, inside `class TestStreamingWiring` (after the existing `test_second_stream_starts_clean` method, keeping the same indentation level):

```python
    def test_first_delta_expands_stream_preview(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("Hello")
        assert app._expand_stream_preview.called

    def test_expand_fires_only_once_per_segment(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("Hel")
        callbacks.on_assistant_text_delta("lo")
        callbacks.on_reasoning_delta("hmm")
        assert app._expand_stream_preview.call_count == 1

    def test_stream_end_collapses_when_expanded(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("Hello")
        callbacks.on_stream_end()
        assert app._collapse_stream_preview.called

    def test_stream_end_does_not_collapse_when_never_expanded(self):
        """A stream segment with zero deltas (e.g. straight to a tool call)
        never expanded ConversationPane's sibling, so it must not toggle it
        back on either — there's nothing to undo."""
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_stream_end()
        assert not app._collapse_stream_preview.called

    def test_second_segment_expands_independently(self):
        """Each stream segment tracks its own expanded state from a clean
        slate — a segment that didn't expand mustn't suppress expansion on
        the next one, and vice versa."""
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_stream_end()  # no deltas: never expanded
        app._expand_stream_preview.reset_mock()
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("now streaming")
        assert app._expand_stream_preview.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_tui_callbacks.py -v`
Expected: the five new tests FAIL — `app._expand_stream_preview` / `app._collapse_stream_preview` are never called yet (MagicMock `.called` is `False`).

- [ ] **Step 3: Implement the wiring in `tui/callbacks.py`**

In `tui/callbacks.py`, modify the streaming section (currently lines 59–88):

```python
    _stream = {
        "reasoning": "", "text": "",
        "last_flush": {"reasoning": 0.0, "text": 0.0},
        "expanded": False,
    }
    _FLUSH_INTERVAL = 0.05

    def _flush_stream(kind: str = "text", force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - _stream["last_flush"][kind]) < _FLUSH_INTERVAL:
            return
        _stream["last_flush"][kind] = now
        app.call_from_thread(preview.show_progress, _stream["reasoning"], _stream["text"])
        if not _stream["expanded"]:
            _stream["expanded"] = True
            app.call_from_thread(app._expand_stream_preview)

    def on_stream_start() -> None:
        _stream["reasoning"] = ""
        _stream["text"] = ""
        _stream["last_flush"] = {"reasoning": 0.0, "text": 0.0}
        _stream["expanded"] = False

    def on_assistant_text_delta(chunk: str) -> None:
        _stream["text"] += chunk
        _flush_stream(kind="text")

    def on_reasoning_delta(chunk: str) -> None:
        _stream["reasoning"] += chunk
        _flush_stream(kind="reasoning")

    def on_stream_end() -> None:
        if _stream["reasoning"] or _stream["text"]:
            _flush_stream(force=True)   # final render with the complete text
        app.call_from_thread(preview.finish)
        if _stream["expanded"]:
            app.call_from_thread(app._collapse_stream_preview)
```

(Only `_stream`'s initial dict literal, `_flush_stream`, `on_stream_start`, and `on_stream_end` change — `on_assistant_text_delta` and `on_reasoning_delta` are shown above unchanged, for context, so the diff is unambiguous.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_tui_callbacks.py -v`
Expected: all tests PASS, including the pre-existing `TestStreamingWiring` tests (unaffected — they never assert on `app._expand_stream_preview`/`app._collapse_stream_preview`, and `app` is a `MagicMock` so the new calls are absorbed harmlessly).

- [ ] **Step 5: Commit**

```bash
git add tui/callbacks.py tests/test_tui_callbacks.py
git commit -m "feat(tui): expand StreamPreview to full window on first streamed delta"
```

---

### Task 4: Full regression pass and manual smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `conda run -n dagi python -m pytest tests/ -v`
Expected: all tests PASS (no regressions in `test_streaming_loop.py`, `test_agent_callbacks.py`, `test_tui_notifications.py`, `test_tui_callbacks.py`, `test_stream_preview.py`, or elsewhere).

- [ ] **Step 2: Manual smoke test in a real terminal**

Run: `conda run -n dagi python tui.py` (or however the TUI is normally launched — check `README.md` if unsure) with a model that has `stream: true`. Send a prompt that produces a long response (e.g. "write a 50-line explanation of X"). Confirm:
- As soon as text starts streaming, `ConversationPane` disappears and the preview fills the window down to the running-indicator/prompt.
- The preview shows more than 12 lines of scrollback once it has enough content, growing with terminal height.
- When the turn finishes, the preview disappears and the full conversation (including the final message) reappears exactly as before this change.
- Resize the terminal mid-stream (if your terminal allows it) and confirm the preview's visible line count adapts.

- [ ] **Step 3: Update project docs**

Use the `update-project-context` skill to refresh `AGENTS.md`, and manually update `README.md` / `TODO.md` per `CLAUDE.local.md` project instructions, noting that `StreamPreview` now expands to full-window during active streaming.

- [ ] **Step 4: Final commit (docs only, if the above steps changed any doc files)**

```bash
git add AGENTS.md README.md TODO.md
git commit -m "docs: note StreamPreview full-window expand behavior"
```
