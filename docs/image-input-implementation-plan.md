# Dagi GUI image input: implementation handoff

Date: 2026-09-13

Status: detailed implementation proposal. The user requested this handoff for another agent.
Research and planning are complete; feature implementation and live API verification have not
been performed. Proposed defaults below are application choices, not provider guarantees.

## 1. Outcome and scope

Allow a user to paste a screenshot into the PySide GUI composer, inspect/remove its thumbnail,
add optional text, and submit it to a vision-capable OpenAI-compatible Chat Completions model.
The image bytes must reach the provider, remain available on later turns, and survive restart.

Include in the first version:

- Ctrl+V and context-menu Paste for clipboard image pixels.
- Copied local PNG/JPEG files; allow multiple image files in one paste.
- Text with images, image-only messages, multiple images, and removable previews.
- Ordinary turns and input at a confirmed paused-loop checkpoint.
- Durable image storage, history labels, sent-image previews, resume, and inherited context.
- Configurable bounds, model compatibility checks, actionable errors, and regression tests.

Leave these for separate work: image generation, remote URL downloading, HTML-image scraping,
drag-and-drop, an attachment file-picker button, image editing, GIF/video, and new attachment
input in TUI/CLI/Telegram. Existing text callers must continue to work. These other interfaces
must safely display and resume shared history containing images.

For v1, reject attachments on local commands and live `ask_user` replies without consuming
the draft. Do not silently convert an image to its filename or base64 text as a tool answer.

## 2. Verified starting points

Paths below are relative to the repository root. Read the current files before editing;
line numbers and exact implementation details may change after this handoff.

| Surface | Current behavior and required attention |
| --- | --- |
| `pyside_gui/prompt_input.py` | `PromptInput(QPlainTextEdit)` emits `Signal(str)`. Enter submits nonempty text and clears immediately. |
| `pyside_gui/app.py` | `_on_input_submitted` routes commands, pending questions, pause injection, and ordinary dispatch. `_agent_work` invokes `AgentLoop.run`. |
| `pyside_gui/conversation.py` and `resources/conversation.js/.css` | User message rendering accepts text. QWebEngine loads a local template; emote images already use local URLs. |
| `agent/loop.py` | `run(task: str)` uses string operations, logs the task, records it in `SessionTracker`, and generates a slug. `_build_request_messages` returns history to Chat Completions. |
| `agent/session_log.py`, `session_surface.py` | The event log owns state; `_messages` is derived. Surface projection deep-copies content and currently describes itself as OpenAI-ready. |
| `agent/session_store.py`, `session.py` | Event sidecar and legacy tracker JSONL are separate persistence paths. `finish(raw_messages=...)` also persists history. |
| `agent/history.py` | Resume reads legacy `session_end.raw_messages`; some labels call `str(content)`. Copy extraction supports text parts but drops image-only messages. |
| `agent/context_spec.py`, `_compaction.py` | Context reconstruction projects log events; compaction constructs a retroactive inherited prefix separately from normal request assembly. |
| `agent/loop.py`, `tools/subagent_main.py` | Fork snapshots preserve provider request identity; inherited children seed from snapshot messages. |
| `tools/compact/_tail_boundary.py` | `estimate_tokens` returns 200 for any content list. Actual step-boundary calculation uses provider token totals and average tokens per step. |
| `tui/utils.py` | `_breakdown`, also used by the GUI bridge, extracts text parts and currently ignores image cost. |
| `agent/_loop_config.py`, `config_loader.py`, `_model_switch.py` | New image settings must resolve through configuration and follow the selected model, including tier switches. |

The configured default found during research is `current-free-openrouter`, model
`openrouter/free`. No live image request has established compatibility for this route.

## 3. API contract

Use the existing `client.chat.completions.create(...)` path, including streaming. A user
message with images has a content array, with text first when present:

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "Explain this screenshot"},
    {
      "type": "image_url",
      "image_url": {"url": "data:image/png;base64,<base64 of PNG bytes>"}
    }
  ]
}
```

Omit the text part for an image-only message. Preserve the existing string content for
text-only messages. Do not add synthetic user text solely to satisfy slug generation.
Omit `detail` by default for compatibility; an explicit configured value may be supported.
Do not use Responses API `input_image` fields in Chat Completions requests.

The SDK serializes this structure into the HTTPS JSON request body. No multipart upload,
public hosting, Files API call, or server access to local paths is needed. Base64 length is
`4 * ceil(byte_count / 3)` before the short data-URL prefix and JSON overhead.

Sources checked during planning:

- [OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision)
- [OpenRouter image inputs](https://openrouter.ai/docs/guides/overview/multimodal/image-understanding)
- [Qt QPlainTextEdit paste hooks](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QPlainTextEdit.html)
- [Qt QMimeData image data](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QMimeData.html)

Provider and model image support still require verification. Compatibility with the OpenAI
text API does not establish vision support or a universal request-size limit.

## 4. Data ownership and representation

Use three representations with explicit conversion boundaries. Keep Qt objects out of the
agent core, persisted JSON, and worker-thread submission payloads.

### Composer draft and submission

Introduce frozen, Qt-independent value objects, with keyword-only fields where appropriate:

```python
ImageAttachment(data: bytes, mime_type: str, width: int, height: int, name: str)
UserSubmission(text: str, images: tuple[ImageAttachment, ...] = ())
```

Exact names may match existing conventions. A submission is a snapshot: subsequent editor
changes, clipboard changes, or mutation of a source image must not change it. QImage/QPixmap
are confined to clipboard processing and previews. Use immutable encoded bytes at handoff.

Keep `AgentLoop.run(str)` and `inject_and_resume(str)` backward compatible by normalizing
strings internally. Accept the new value object through the same entry points.

### Durable conversation representation

Store normalized image bytes once in a project-local content-addressed asset store:

```text
<project>/.dagi/attachments/<sha256-of-exact-bytes>.png
```

Store a versioned internal content part in user-message event content:

```json
{
  "type": "dagi_image",
  "version": 1,
  "sha256": "<64 lowercase hex characters>",
  "mime_type": "image/png",
  "byte_size": 12345,
  "width": 1200,
  "height": 800,
  "name": "Screenshot 1"
}
```

The digest determines the path; persisted content must not supply an arbitrary filesystem
path. If detail is configured when attaching, persist it as an optional `detail` field on
the reference; later configuration changes must not rewrite that choice. Add
`.dagi/attachments/` to Git ignores. Resolve the store from the owning project,
never the current process working directory or a session filename that can be renamed.
Moving a project together with `.dagi/` preserves references. Copying just a session JSONL
does not include its assets; report missing assets explicitly.

Write bytes atomically before appending any event that references them. Concurrent insertion
of identical bytes must produce one valid asset. Existing hash paths must be verified, not
blindly trusted or overwritten. Verify digest and byte size when loading assets. Reject
escaping paths and symlink/junction escapes. Never re-encode an asset on later requests.

Drafts stay in memory. Removing a draft thumbnail releases that draft's bytes. Persisted
assets are retained in v1; do not garbage-collect them on conversation clear, session rename,
compaction, or branch completion because other history may still reference them. Failed
event writes may leave an unreferenced asset; this is preferable to a dangling reference.

### Provider representation

Implement one reusable `materialize_messages(messages, store)` conversion which returns
deeply independent message dictionaries and replaces internal image parts with data URLs.
Preserve message/part order and all unrelated fields, including assistant tool calls and
reasoning fields. Do not recursively reinterpret arbitrary tool output or text as assets.
Unknown internal image versions fail with a useful error; they never reach the API.
Route materialization and preflight exceptions through normal user-visible error handling;
the current request-building call precedes the SDK-specific inner `try` block.

Use it for normal requests, stable fork capture, and reconstructed compaction prefixes.
`_last_request_snapshot` must contain the actual materialized provider request. Observers
must receive independent data so a callback cannot mutate the outgoing request or history.

This means the durable surface may contain internal image references. Update misleading
OpenAI-ready/byte-identical docstrings in `session_surface.py` and `context_spec.py`: provider
equivalence is established after materialization. Keep both modules free of filesystem I/O.

## 5. Clipboard and composer behavior

Retain `QPlainTextEdit`; add a small attachment strip as part of the surrounding composer.
Do not replace the editor with rich text solely to embed images. Give each thumbnail a
visible remove control, accessible label, and image dimensions. Keep text focus after paste.

Override `canInsertFromMimeData` and `insertFromMimeData` so keyboard and menu paste share
the implementation. Use this deterministic precedence:

1. Clipboard exposes image pixels: copy and validate the image, normalize to PNG, attach once.
2. Otherwise, clipboard exposes local file URLs: accept a batch only when every entry is a
   supported readable image. Decode and normalize each; reject the whole batch on failure.
3. Otherwise, use the existing text paste behavior. Do not fetch remote URLs or parse HTML
   for remote images. Unsupported local-file batches get an error and leave the draft intact.

When clipboard data offers both pixels and text/HTML, attach the image once; do not also
insert its alternate URL or HTML representation. Existing typed text remains untouched.
Use Qt image decoding, validate a non-null result, bound file bytes and decoded dimensions,
and encode to PNG once. Preserve screenshot resolution and transparency within limits.
Do not silently downscale, crop, or recompress later. Reject excessive inputs with the limit
and a suggested remedy. Limit file dimensions before full decode where Qt exposes them;
check the decoded result and encoded byte size as well.

Perform expensive file reading/decoding/PNG encoding off the UI thread using detached input
data. Clipboard access and QPixmap/widget operations stay on the GUI thread. While a paste
batch is processing, disable submission and show a short processing state. Commit the whole
batch on success, or retain the preceding draft on failure. Discard stale results after a
composer/session reset using a draft-generation identifier. Do not introduce a general job
framework for this small operation.

Change submission to emit `UserSubmission` through `Signal(object)` (or equivalent). Enter
submits when text or images exist. Preserve current modified-Enter behavior. Attachment
removal has its own control; normal text undo/redo remains normal text undo/redo.

## 6. Submission acceptance and failure behavior

Separate draft acceptance from completion of the model turn. The editor must stop clearing
itself immediately when it emits a submission.

| Situation | Required behavior |
| --- | --- |
| Empty text and no images | No submission. |
| Validation failure or model explicitly rejects image input | Explain why; preserve text and all thumbnails; no user event or provider call. |
| Worker running normally | Preserve draft and report that it cannot be submitted yet. |
| Local command/exit alias with images | Reject without executing command or clearing images. Text-only command behavior stays unchanged. |
| Live `ask_user` with images | Reject without setting its event or modifying its answer container. |
| Stale `ask_user` sink | Retire it using the existing guard, then route the submission normally. |
| Confirmed paused checkpoint | Persist and append the full submission exactly once, then resume. |
| Ordinary accepted turn | Persist assets and append user content exactly once, acknowledge acceptance, then clear the matching draft and show the sent message. |
| Persistence failure | Show error; preserve draft; do not call the provider with missing assets. |
| API failure after acceptance | Keep the accepted message and its images in history; preserve the existing pause/retry flow and surface the error. Do not reinsert the same message automatically. |

Use a submission identifier for acceptance acknowledgement so a late worker signal cannot
clear a newer draft. Add a GUI-thread acknowledgement through the existing bridge or a
focused signal. Do not mutate widgets directly from worker callbacks. Dispatch must prevent
double submission while acceptance is pending. Re-enable input on every rejected/error path.

Perform local/model preflight and asset persistence before opening/appending the new human
turn where practical. If any failure happens after opening a turn, close it through existing
error handling; do not leave an open turn with no worker. For pause injection, confirm the
existing safe checkpoint before changing log state and resume only after append succeeds.

Provider retries resend the already accepted history. A later text instruction after a paused
failure adds one new message, not another copy of the original image. Avoid a new resend UI
or event-log rollback mechanism in this feature.

## 7. History, forks, model changes, and compaction

- Pass structured content to both the event log and `SessionTracker.record_user`; widen
  relevant annotations. Keep `finish(raw_messages)` reference-based for newly submitted
  images so legacy tracker output does not duplicate base64 payloads.
- Old text-only sessions and existing OpenAI multipart messages must still load. Preserve
  pre-existing wire `image_url` parts unchanged unless lossless normalization is proven.
- Inherited fork snapshots may intentionally contain base64 because they are actual provider
  request snapshots. The child can import dagi's canonical PNG data URLs into its own project
  store during seed normalization, provided materializing them reproduces the exact original
  URL and fields. Do not decode and re-encode image pixels. Preserve unknown/legacy forms.
  Temporary fork files remain governed by the existing cleanup lifecycle.
- Apply the same materializer to `_compaction.py`'s reconstructed `prefix_msgs` before
  building the fork snapshot. Normal `_build_request_messages` coverage alone is insufficient.
- Preserve exact inherited image content, ordering, detail settings, and request identity.
  Isolated children do not gain image history unless explicitly supplied by their existing
  context mode. Do not silently fall back to a text-only worker for inherited image context.
- Compaction may replace old image-bearing messages with its normal textual summary. The
  summarizer must receive the images first, recent tail images remain intact, and original
  asset files/raw events remain available. Do not promise lossless visual recall from a summary.
- Restore references against the selected session's owning project. Validate unresolved
  references before a provider request and identify missing/corrupt attachments. Never omit
  them silently or send a filesystem path as `image_url`.
- Use shared text/attachment-label extraction in history titles, turn lists, copy views, and
  TUI resume rendering. An image-only message should appear as `[1 image]`, not an empty row
  or a dictionary/base64 string. Copying text uses labels for attachments, not image bytes.
- Render newly sent GUI images from validated local asset URLs using structured arguments
  and normal JSON/DOM escaping. Do not inject filenames as raw HTML. The existing restore UI
  only announces restored context; a full historical transcript renderer is outside scope.
- Share image-aware token estimation between existing consumers: count text and tool-call
  arguments normally, add an explicit estimate per image, never count base64 characters.
  Keep estimates labeled approximate. Provider usage remains authoritative. Do not rewrite
  the existing step-based compaction algorithm as part of this feature.

## 8. Configuration and compatibility

Add a small typed image-input configuration value to `AgentConfig`, resolved from global
defaults with per-model overrides. Suggested starting defaults:

| Setting | Proposed default | Meaning |
| --- | --- | --- |
| `supports_images` | `null` | `false` blocks; `true` permits; unknown permits an attempt with clear provider errors. |
| `image_input.max_images_per_message` | 4 | Composer/submission limit. |
| `image_input.max_image_bytes` | 8 MiB | Bound both source file and normalized PNG bytes. |
| `image_input.max_pixels` | 24,000,000 | Decoded pixel budget per image. |
| `image_input.max_request_image_bytes` | 20 MiB | Total data-URL bytes for images in the entire outgoing history. |
| `image_input.detail` | omitted | Provider default; validate explicit supported values. |
| `image_input.estimated_tokens_per_image` | 1,024 | Configurable heuristic, not an upper bound or billing prediction. |

Validate positive integer bounds and explicit boolean/null capability values; do not coerce
the string `"false"` to true. Unknown capability is not a certification. Do not infer vision
support from provider hostname or a model-name substring. Do not change the user's default
model or silently route an image to a different provider.

Apply request image-size checks to all history images, not only new attachments. A provider
may enforce a smaller total JSON-body limit, so handle HTTP 413 and validation responses
clearly. Do not automatically discard older images to make a request fit.

Model-tier changes must carry capability/limits/detail configuration and preserve recorded
detail choices for old images. If live history has images and a target model explicitly
disallows them, reject the switch before changing client/config state. Check GUI model
selection and inherited-config construction too. Unknown targets may try the request.

Keep existing transient retry rules. Unsupported content, malformed image, and size-limit
errors should be actionable and should not be retried blindly as transient failures. Avoid
including base64 or credentials in displayed/logged exception details introduced by this work.

## 9. Suggested implementation sequence and file ownership

Implement in these coherent stages, adapting module names to existing conventions:

1. **Core representations and asset store.** Add small Qt-free modules such as
   `agent/user_input.py` and `agent/image_assets.py` for value objects, validation of metadata,
   durable references, atomic storage, and exact-byte materialization. GUI decoding validates
   image contents; the store validates reference format, bounds, size, and hash. No Qt import
   or new image-decoding dependency is required in headless core for these operations.
2. **Loop and persistence.** Wire normalization, acceptance, string compatibility, tracker
   content, provider materialization, and deep-copy isolation. Keep slug input text-only;
   image-only first turns use a local fallback label without another vision/API request.
3. **Fork/resume/configuration.** Wire alternate request paths, inherited normalization,
   model-switch preflight, history labels, and token estimates before exposing GUI input.
4. **GUI composer and routing.** Add a focused attachment/paste helper module, previews,
   immutable submissions, routing checks, and bridge acknowledgements. Keep `app.py` glue
   small; do not place normalization/storage logic in an already oversized window class.
5. **Sent-image rendering and errors.** Extend conversation Python/JS/CSS, verify useful
   messages, and ensure every failure route restores usable input.
6. **Integration verification and documentation.** Run the tests below, perform an opt-in
   live endpoint smoke test, and record actual implementation/results in the wiki.

Inspect `agent/session_events.py`/`session_store.py` format gates before persisting the new
internal part. Advance the event format from version 2 to 3, retaining read support for
existing supported versions; old readers must reject the new format. Also add an explicit
content-format marker to legacy tracker records and validate it in the new history reader.
Do not claim old executables can resume new image sessions.

## 10. Verification and acceptance criteria

Write tests that fail when images are lost, duplicated, mutated, or sent incorrectly.
Use tiny programmatically generated fixtures; no personal screenshots in test assets.

| Test group | Required assertions |
| --- | --- |
| Wire payload | Decode outgoing data URL and compare exact PNG bytes; verify MIME, part order, multiple images, image-only, and unchanged text-only shape. |
| SDK boundary | Use an OpenAI client with mocked HTTP transport to inspect actual serialized JSON without real credentials/network. Exercise streaming and nonstreaming paths. |
| Asset store | Atomic write, duplicate insertion, concurrent identical writes, hash mismatch, missing file, invalid reference/version, traversal/junction escape, and rename-independent paths. |
| Persistence | Round-trip event log and legacy `raw_messages`; remove original source file and clear clipboard, then resume and obtain identical wire image bytes. |
| History | Image-only labels remain visible; titles/copy/TUI views never render base64 or raw reference dictionaries. |
| Isolation | Mutating callback messages/provider kwargs cannot alter session state or a later request. |
| Fork and compaction | Normal/stable/spawn/retroactive prefixes contain the same image URLs; child seed round-trip preserves them; retained tail images survive summary replacement. |
| Limits and models | Count history-wide image bytes; reject explicit unsupported model before send/switch; allow unknown capability; preserve prior detail fields after model changes. |
| Paste | Pixels and local-file batches work; text still pastes; pixel+HTML data attaches once; invalid/oversized batch adds nothing; stale async decode cannot alter a new draft. |
| Composer | Enter with image only, thumbnail removal, modified Enter, double-submit prevention, acknowledgement clearing only matching draft. |
| Routing/errors | Busy worker, commands, live/stale question, paused checkpoint, persistence failure, and API rejection retain the correct draft/history and leave input usable. |
| Accounting | More text/images increases estimates; huge base64 strings do not inflate text tokens; provider-reported usage remains unmodified. |

Extend relevant existing suites: `tests/test_session_surface.py`, `test_session_log.py`,
`test_session_store.py`, `test_session_tracker.py`, `test_history.py`, fork/context tests,
compaction integration tests, and `pyside_gui/tests/test_pending_ask.py`/`test_session_history.py`.
Create focused image/paste tests only where existing files have no appropriate home.
`tests/test_prompt_input_multiline.py` tests the Textual widget, not the PySide composer.

Use `DEFAULT_PYTHON_ENV` (`dagi`) for Python and package operations. Follow repository test
configuration; the pytest plugin disable name is `no:pytest-qt`. Some GUI tests require a
fully activated conda environment on Windows for Qt DLL loading. If isolating tests from the
RAM watchdog with `--noconftest`, verify required fixtures are still available. Do not report
GUI coverage as passed if Qt could not load.

Manual Windows checks: paste from Snipping Tool, copy a PNG/JPEG file in Explorer, paste
ordinary text, remove images, send without text, reject an excessive image, and restart then
ask a follow-up about a previously sent image. Inspect both collapsed and expanded composer
layouts and sent thumbnails at normal display scaling.

Live smoke test: use a configured vision-capable model and a synthetic image with distinctive
text/shapes. Verify the model can describe it and answer a subsequent question from history.
Record endpoint/model, streaming mode, and outcome without exposing credentials or base64.
Keep this test opt-in; if credentials/access are unavailable, report it explicitly as unrun.

Done means all automated checks applicable to the change pass, GUI paste is visually verified,
durable restart/fork behavior is verified, and the live endpoint result or remaining external
verification gap is clearly reported. Update wiki/AGENTS per project instructions. Do not
commit, push, switch/create branches, or discard existing work without user authorization.
