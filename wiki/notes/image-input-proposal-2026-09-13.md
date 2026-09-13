# Image Input Proposal for the PySide GUI — 2026-09-13

Status: research complete; proposed design only. The image-input implementation has not been
approved or performed. Provider endpoint/model behavior has not been live-tested.

## Scope and current behavior

The requested research covered image API input, GUI backend transport, and clipboard paste. The
following current-state findings came from supplied source inspection; no implementation work was
performed as part of this investigation:

- `pyside_gui/prompt_input.py` uses `PromptInput`, a `QPlainTextEdit` that emits submitted text as
  `Signal(str)`. Enter submits only nonempty text and clears the editor immediately.
- `pyside_gui/app.py` routes submissions through `_on_input_submitted` and `_dispatch_agent` to
  worker `_agent_work`, which calls `AgentLoop.run(task)`. Other text-only paths include pending
  ask responses and paused-agent injection.
- `agent/loop.py` strips the task, uses a slug generator that slices task text, logs user message
  content, and builds provider request messages from history. `agent/session_surface.py`
  deep-copies content without string conversion; `agent/history.py` stringifies content in some
  labels. `agent/session.py` records user content with a `str` type annotation.
- `.dagi/config.yaml` defaults `default_model` to `current-free-openrouter`, which resolves to
  `openrouter/free` in the supplied inspection.
- `tools/compact/_tail_boundary.py` has a fixed-200-token `estimate_tokens` helper for list-valued
  content, while live `compute_tail_boundary` uses provider `prompt_tokens` averaged by step. Do
  not treat the helper as controlling live compaction boundaries. `tui/utils._breakdown` also
  ignores image cost. The implementation handoff should keep these distinct.

## API and clipboard evidence

The supplied research of the official OpenAI image guide confirmed Chat Completions content arrays
can include text and an `image_url` object. Its URL may be a base64 data URL or a public image URL,
and the selected model must support vision. See [OpenAI image and vision guide](https://developers.openai.com/api/docs/guides/images-vision).

The supplied research of the official OpenRouter image-understanding guide confirmed its generic
multimodal chat-completions format accepts image URLs or base64 image data. Per-model and per-provider
limits vary, so the configured `openrouter/free` route and its resolved model still need a live
capability check. See [OpenRouter image understanding](https://openrouter.ai/docs/guides/overview/multimodal/image-understanding).

The supplied Qt documentation research confirmed `QPlainTextEdit` supports `canInsertFromMimeData`
and `insertFromMimeData`, while `QMimeData` exposes `hasImage()` and `imageData()`. These provide
hooks for image clipboard paste while retaining ordinary text paste. See the [Qt for Python
QPlainTextEdit reference](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QPlainTextEdit.html)
and [QMimeData reference](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QMimeData.html).

## Proposed design — unapproved

- Keep the plain-text editor and add removable attachment thumbnails. Intercept image MIME data and
  local image-file clipboard URLs; normalize clipboard pixels to PNG, while allowing normal text
  paste unchanged.
- Submit an immutable text-plus-attachments draft. Accept image-only submissions, and clear the
  draft only after the GUI accepts it. Preserve the draft if validation or a local command rejects
  the attachments.
- Persist image bytes as immutable assets with stable references. Materialize `image_url` data URLs
  at the provider boundary, so persisted history, retries, resume, forks, and compaction retain the
  same image content. Do not put base64 into human-facing displays or count it as ordinary text.
- Define image handling for paused-agent injection and pending `ask_user` responses. Keep attachment
  behavior explicit for local commands that do not accept images.
- Add configurable image size/count limits, vision-capability handling, and clear errors from
  providers. For image-aware estimates, use text length and image count or known image dimensions;
  do not imply this estimate replaces live provider-token measurements at the compaction boundary.

## Implementation verification to perform after approval

Verify submitted payload bytes and ordering, text-only regressions, clipboard image and file-URL
paste, attachment removal, image-only submissions, and draft preservation on rejection. Verify
persistence and identical references through resume, forks, retries, and compaction; check that
human-facing history omits base64 and token estimation accounts for text and images. Run a live
endpoint smoke test against the configured route/model and test clear errors when image capability
or limits are unavailable. No such tests or endpoint checks were performed for this proposal.

## Implementation handoff — proposed, still unapproved

The following details refine the proposal for a future implementation. They are design guidance,
not evidence of approval or completed work:

- Represent a submission as immutable `UserSubmission` and `ImageAttachment` values. Normalize
  clipboard images to PNG in Qt, then persist them as project-local, content-addressed assets under
  `.dagi/attachments`. Use versioned internal `dagi_image` reference parts in session messages and
  materialize them as provider image parts at the provider boundary.
- Route normal requests, stable requests, and compaction-fork requests through shared
  `materialize_messages`. Session surfaces can remain pure but will contain internal references.
  The event log and `SessionTracker.finish(raw_messages)` must compact references too. The proposal
  is event format 2 to 3 with backward read support, plus a legacy tracker content-format marker.
  `context_spec` and `_compaction` rebuild prefixes separately; `_last_request_snapshot` freezes the
  actual provider payload, so account for each path explicitly.
- Import inherited canonical PNG data URLs losslessly and preserve their exact wire URL, ordering,
  and detail value. Persist optional image detail on each reference at submission time so later
  config changes do not alter old requests. Leave other legacy image forms unchanged. Do not
  automatically delete durable image assets during compact or clear because session history and
  forks can still reference them.
- Clear a GUI draft only after its assets are persisted and the user message is appended. If busy,
  blocked by a live `ask_user`, or rejected as a local command, retain the draft with its images.
  Retire stale ask sinks; inject pause-time input only at a safe checkpoint. If an accepted provider
  request fails, retain its history without resending it as a duplicate.
- Treat default config values as policy choices, not provider guarantees: `supports_images: null`
  permits an attempted request, while `false` blocks it; proposed defaults are four images per
  message, 8 MiB per image, 24 million pixels, and 20 MiB of data-URL bytes across the full request.
  Omit detail by default and use roughly 1,024 tokens per image as a configurable estimate. Keep
  the existing default model unchanged.
- Verification should also cover decoded payload bytes, asset-store integrity, persistence/resume,
  fork and compaction materialization, GUI paste/routing/rejection behavior, and provider errors.
  A live test may be opt-in and use a synthetic image. `tests/test_prompt_input_multiline` is a
  Textual test, not a PySide GUI test. None of these implementation checks or a live endpoint test
  has been performed.

[Notes](index.md) | [Project wiki](../index.md)
