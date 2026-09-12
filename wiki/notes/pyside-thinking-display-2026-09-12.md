# PySide Thinking Display — 2026-09-12

The PySide conversation view now keeps a short live reasoning preview and expands it into a
complete Markdown block as the assistant response progresses.

## Behavior

- `ConversationView` owns the reasoning buffer on the GUI thread. It resets the buffer at
  `stream_start` and when the conversation is cleared.
- While reasoning streams, the displayed plain-text tail is clipped to three wrapped visual
  lines. The preview scrolls to its newest end.
- The first nonempty answer delta renders the full accumulated reasoning as Markdown. If the
  stream ends without answer text, the full block renders at `stream_end`, including
  reasoning-only, tool-only, and partial-ended streams.
- Later reasoning deltas refresh the same block; the next completed stream receives a separate
  block. Nonstreaming `append_reasoning` also uses Markdown rendering.
- The JavaScript view keeps one thinking block before the answer and removes an empty final
  assistant bubble. Existing main-window duplicate suppression remains in place.
- Reasoning Markdown disables embedded HTML, and quotes in fenced-code language attributes are
  escaped.

## Verification

`test_conversation_reasoning.py` exercises actual Qt WebEngine rendering for the wrapped and
explicit three-line tail, the first-answer transition, completion without duplicate blocks,
successive reasoning-only turns, literal HTML, clearing and late reasoning, empty and text-only
turns, and main-window duplicate suppression. `test_markdown_renderer.py` covers fenced
language-attribute escaping.

The focused GUI regression run reported 28 passed and one preexisting unrelated failure:
`test_bridge.py::test_expression_and_process_snapshots_emit_as_objects` expects the missing
`AgentBridge.expression_changed` signal. Offscreen screenshots inspected with `--disable-gpu`
showed the three-line preview and full heading, bold, code, and list rendering. A sandbox-local
WebEngine page attempt failed; the GUI tests passed outside the sandbox apart from the unrelated
bridge failure.

[Notes](index.md) | [Project TODOs](project-todos.md) | [Project wiki](../index.md)
