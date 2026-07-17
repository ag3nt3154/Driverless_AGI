# DAGI Streaming Support — Design

## Problem

`agent/loop.py` calls `self.client.chat.completions.create(...)` without `stream=True`. The full
model response (content, tool calls, reasoning, usage) only becomes available after the API
finishes generating it entirely. In the TUI, this means the conversation pane sits idle for the
full generation time and then the whole reply appears at once — there is no "watching it think/type"
feedback during long responses.

## Scope

- TUI (`tui.py`) only. `main.py`, `telegram_bot.py`, and the scheduler are out of scope for this
  change — they must continue to work identically, streaming or not.
- Streams both the visible assistant reply text and the reasoning/thinking content. Tool-call
  arguments are accumulated from stream deltas (required to reconstruct the tool call at all) but
  are not displayed incrementally — only the final tool call is shown, as today.
- Token/cost usage data is best-effort: requested via `stream_options: {"include_usage": true}`,
  but if a provider never sends the trailing usage chunk, the turn's usage is treated as unknown
  (same degraded state that already exists today for providers that omit `usage.cost`).

## Config surface

New `stream: bool` key in `config.yaml`, default `true`, following the same global +
per-model-override pattern as the existing `thinking` key:

```yaml
stream: true   # global default

models:
  some-model:
    stream: false   # per-model override
```

`agent/config_loader.py` resolves this into `AgentConfig.stream: bool` the same way it already
resolves `thinking`.

## `agent/loop.py` changes

### The API call

When `self.config.stream` is true, the `create()` call adds:

```python
stream=True,
stream_options={"include_usage": True},
```

Instead of a single `response` object, the call returns a chunk iterator. A new helper,
`_consume_stream(chunk_iter) -> (message, usage)`, accumulates chunks into the same shapes the
non-streaming path already produces:

- **Content deltas** (`choice.delta.content`) — appended to a running string; each non-empty delta
  also fires `callbacks.on_assistant_text_delta(delta)` immediately (before accumulation
  completes), so the TUI can render incrementally.
- **Reasoning deltas** (`choice.delta.reasoning` or `choice.delta.reasoning_content`, depending on
  provider — OpenRouter uses `reasoning`) — same treatment via
  `callbacks.on_reasoning_delta(delta)`.
- **Tool call deltas** (`choice.delta.tool_calls`) — a list of partial tool-call objects, each
  carrying an `index`. The first delta for a given index carries `id`, `type`, and
  `function.name`; every delta for that index appends to `function.arguments`. Accumulated by
  index into a dict, then converted to the same `list[ChatCompletionMessageToolCall]`-equivalent
  shape used by the non-streaming path once the stream ends.
- **The trailing usage-only chunk** (`chunk.usage`, present when `choice.delta` is empty and
  `include_usage` was requested) — captured as `usage`. If no such chunk arrives before the
  iterator is exhausted, `usage` stays `None` and downstream code treats it exactly like a
  response with missing usage fields today (`getattr(..., "x", 0) or 0` patterns already handle
  `None`).

`_consume_stream` returns a `message`-shaped object (`.content`, `.tool_calls`) and a
`usage`-shaped object, matching `response.choices[0].message` / `response.usage` from the
non-streaming path closely enough that **every line of code after the API-call block is
unchanged** — the ghost-response check, tool dispatch, `tracker.record_assistant`,
`on_token_update`, `on_assistant_text`, `on_reasoning`, compaction accounting, all of it.

`callbacks.on_stream_start()` fires once, right before the first chunk is consumed (only when
`self.config.stream` is true). `callbacks.on_stream_end()` fires once after the iterator is
exhausted (in a `finally`, so it fires even if consumption raises). The existing
`on_assistant_text(full_text)` / `on_reasoning(full_text)` calls still fire afterward with the
complete accumulated text, unchanged from today.

### Error handling

- Errors raised by `create()` itself (before iteration starts) are handled by the existing
  retry/backoff block, unchanged.
- Errors raised **while iterating** the stream (connection drop mid-generation) are caught in
  `_consume_stream`'s caller, treated as an `openai.APIConnectionError`-equivalent, and routed into
  the same retry path: discard the partial accumulation, apply backoff, retry the whole `create()`
  call from scratch. This reuses `_error_retries` / `api_error_retries` — no new retry counters.
- The ghost-response check (empty content + no tool calls + zero prompt tokens) runs on the fully
  accumulated `message`/`usage` after the stream completes, identical logic to today.

### New callbacks

Added to `AgentCallbacks` (`agent/loop.py`), all with no-op defaults:

```python
on_stream_start:          Callable[[], None]
on_stream_end:            Callable[[], None]
on_assistant_text_delta:  Callable[[str], None]
on_reasoning_delta:       Callable[[str], None]
```

Because defaults are no-ops, `main.py`, `telegram_bot.py`, and the scheduler need zero changes —
their callback sets simply never populate these fields and nothing streams for them at the
callback level (though the underlying API call may still be a streaming call if `config.stream` is
true; they just consume it as if it were blocking, since they only ever read the final
`on_assistant_text`/`on_reasoning`/`on_token_update` calls).

## TUI changes

### Why not just write to `RichLog` repeatedly

`ConversationPane` extends Textual's `RichLog`, which is append-only — each `.write()` call renders
its argument to lines and appends them; there is no supported way to replace or update a
previously-written entry. Streaming by repeatedly calling `append_assistant()` would each time
write a *new*, ever-growing partial-markdown block into scrollback, leaving dozens of stale partial
copies behind instead of one clean message.

### Live widget overlay

A new widget, `StreamingMessage` (`tui/conversation.py` or a new `tui/streaming.py`), holds two
optional live regions — reasoning and assistant text — and is mounted as a sibling below
`ConversationPane` within the conversation container:

- `on_stream_start` → mount `StreamingMessage` (empty).
- `on_assistant_text_delta(chunk)` / `on_reasoning_delta(chunk)` → append to the corresponding
  running string on the widget and refresh its render (Textual re-renders efficiently on
  `update()`; no manual throttling planned unless testing shows flicker/CPU issues, in which case a
  simple time-based throttle — e.g. skip refresh if <50ms since last — can be added).
- `on_stream_end` → unmount `StreamingMessage`.
- `on_assistant_text(full_text)` / `on_reasoning(full_text)` (existing callbacks, called right
  after `on_stream_end` today's way) → write the final `Panel`/`Markdown` into `ConversationPane`,
  unchanged from current behavior.

Net effect: while a turn is generating, the user sees a live-updating preview at the bottom of the
conversation; once it completes, that preview disappears and the same permanent panel that exists
today is written into scrollback. No change to scrollback contents or history semantics.

### Wiring

`tui/callbacks.py::build_callbacks` gains handlers for the four new callback fields, following the
existing `app.call_from_thread(...)` pattern used by every other callback in that file.

## Testing

- `agent/loop.py`: unit tests mocking `client.chat.completions.create` to return a canned chunk
  iterator (content-only, reasoning+content, tool-call, usage-omitted, mid-stream connection error)
  and asserting `_consume_stream` reconstructs the same `message`/`usage` shape the non-streaming
  path would have produced from an equivalent single response — plus that ghost-response retry
  still triggers correctly on a stream that ends with empty content/no tool calls/zero prompt
  tokens.
- `tui/callbacks.py`: tests asserting the four new callbacks call the expected `StreamingMessage`
  mount/update/unmount methods via `call_from_thread`.
- Config: test that `stream` resolves correctly at global and per-model level, mirroring existing
  `thinking` resolution tests.
- Regression: existing full test suite must stay green with `config.stream` both `true` (new
  default) and `false` (old code path), confirming the non-streaming path is untouched.

## Non-goals

- No changes to `main.py`, `telegram_bot.py`, `scheduler/`, or any subagent runner — none of them
  wire the new delta callbacks.
- No incremental display of tool-call arguments — only accumulated for correctness, not streamed
  visually.
- No change to how usage/cost is computed once available — only how/when it's captured.
