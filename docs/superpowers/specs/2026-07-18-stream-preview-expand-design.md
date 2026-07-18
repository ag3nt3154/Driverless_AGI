# StreamPreview Full-Window Expand — Design

## Problem

`StreamPreview` ([tui/streaming.py](../../../tui/streaming.py)) renders the live-streaming
assistant reasoning/text, but is permanently capped at `max-height: 14` / `TAIL_LINES = 12`
(see [2026-07-17-dagi-streaming-design.md](2026-07-17-dagi-streaming-design.md) for how streaming
itself was added). On a tall terminal, most of the window sits empty above the conversation pane
while a long response streams in, and only the last 12 lines of the in-progress reply are ever
visible.

## Goal

While a response is actively streaming, `StreamPreview` should expand to fill the full window
(everything except `Sidebar` and the prompt/`#prompt` box), showing as much of the growing
reasoning/text as fits. When the stream ends, it collapses back to today's behavior: hidden, with
the final message written to `ConversationPane` as normal.

## Trigger: deferred to first rendered content, not stream-start

`on_stream_start` fires unconditionally at the start of every streamed turn segment, but some
segments produce no visible reasoning/text before the model moves straight to a tool call. If we
hid `ConversationPane` eagerly on `on_stream_start`, that case produces a blank screen (nothing in
`StreamPreview` yet, `ConversationPane` already hidden). Instead, the expand is triggered from
inside `_flush_stream` (`tui/callbacks.py`) on the first delta actually flushed for a stream
segment, tracked via a new `_stream["expanded"]` flag reset in `on_stream_start` alongside the
existing `reasoning`/`text` reset.

Collapse is symmetric: `on_stream_end` restores `ConversationPane` only if `_stream["expanded"]`
was set, so a segment that never rendered anything doesn't spuriously toggle visibility.

## `StreamPreview` changes (`tui/streaming.py`)

- New `self._expanded: bool = False` instance state.
- `expand()`: sets `self._expanded = True`, `self.styles.height = "1fr"`, `self.styles.max_height
  = None`.
- `finish()`: extended (beyond today's hide + clear) to also reset `self._expanded = False`,
  `self.styles.height = "auto"`, `self.styles.max_height = 14` — restoring the exact collapsed
  CSS defaults.
- Tail-line calculation becomes conditional:
  - Not expanded (default): unchanged — always `TAIL_LINES` (12), byte-for-byte identical to
    today's behavior. This keeps the existing
    [test_stream_preview.py](../../../tests/test_stream_preview.py) assertion
    `len(rendered.splitlines()) <= StreamPreview.TAIL_LINES` valid without modification.
  - Expanded: use `self.size.height` (the widget's actual current rendered height) in place of the
    fixed constant, so a full-window preview shows as much scrollback as fits. Falls back to
    `TAIL_LINES` if `size.height` is `0` (not yet laid out).

## `DagiApp` changes (`tui/app.py`)

Two new methods, mirroring the existing compose-toggle hide/show of `ConversationPane`
(`action_toggle_compose`, [tui/app.py:149](../../../tui/app.py)):

```python
def _expand_stream_preview(self) -> None:
    self.query_one(ConversationPane).display = False
    self.query_one(StreamPreview).expand()

def _collapse_stream_preview(self) -> None:
    self.query_one(ConversationPane).display = True
```

(`StreamPreview.finish()` already resets its own hidden/collapsed state; it is called separately
from `on_stream_end` as it is today.)

## `tui/callbacks.py` changes

```python
def on_stream_start() -> None:
    _stream["reasoning"] = ""
    _stream["text"] = ""
    _stream["last_flush"] = {"reasoning": 0.0, "text": 0.0}
    _stream["expanded"] = False

def _flush_stream(kind: str = "text", force: bool = False) -> None:
    now = time.monotonic()
    if not force and (now - _stream["last_flush"][kind]) < _FLUSH_INTERVAL:
        return
    _stream["last_flush"][kind] = now
    app.call_from_thread(preview.show_progress, _stream["reasoning"], _stream["text"])
    if not _stream["expanded"]:
        _stream["expanded"] = True
        app.call_from_thread(app._expand_stream_preview)

def on_stream_end() -> None:
    if _stream["reasoning"] or _stream["text"]:
        _flush_stream(force=True)
    app.call_from_thread(preview.finish)
    if _stream["expanded"]:
        app.call_from_thread(app._collapse_stream_preview)
```

All calls follow the existing `app.call_from_thread(...)` pattern used by every other cross-thread
UI touch in this file — no new threading primitives.

## Not touched

- The running-indicator spinner bar (`#running-indicator`) and the prompt box (`#prompt`) are
  unaffected — they are not part of "full window minus sidebar/input," they remain the thin status
  strip between the preview and the prompt.
- Compose mode (`action_toggle_compose`) is unaffected: it is already blocked while the agent
  worker thread is alive (except during a pending `ask_user`, which cannot overlap with active
  streaming since the agent thread is blocked waiting on the user's answer). No interaction between
  the two hide/show mechanisms is possible.
- `main.py`, `telegram_bot.py`, and the scheduler: out of scope, as with the original streaming
  feature — they don't use `StreamPreview` or `ConversationPane`.

## Testing

- `tests/test_stream_preview.py`: extend with
  - `expand()` sets `styles.height == "1fr"` and clears `max_height`.
  - `finish()` after `expand()` restores `styles.height == "auto"` and `styles.max_height == 14`,
    and `self._expanded is False`.
  - `_render_tail` while expanded uses `self.size.height` instead of `TAIL_LINES` (mock/set
    `size.height` on the test widget and assert the returned line count matches).
  - Existing collapsed-mode assertions (`TAIL_LINES` cap, hidden by default, etc.) stay green
    unmodified.
- `tests/test_agent_callbacks.py` (or wherever `build_callbacks` is tested): assert
  `_expand_stream_preview` fires exactly once per stream segment on the first flush, not on
  `on_stream_start`, and `_collapse_stream_preview` fires only when a segment actually expanded.

## Non-goals

- No user-facing keybinding to manually expand/collapse — this is fully automatic, tied to active
  streaming only (per user decision during design).
- No change to `TAIL_LINES`'s role as the collapsed-mode cap.
- No change to the running-indicator or prompt box layout/sizing.
