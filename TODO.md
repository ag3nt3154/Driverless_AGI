# TODO

## In progress

- **Image input, stage 5 of 6 done** (see `docs/image-input-implementation-plan.md`).
  Stage 1 landed: `agent/user_input.py` (Qt-free `ImageAttachment`/`UserSubmission`
  value objects) and `agent/image_assets.py` (`ImageRef`, `ImageAssetStore`,
  `materialize_messages` — content-addressed store under `.dagi/attachments/`,
  atomic writes, hash/size validation, path-traversal guards). Covered by
  `tests/test_image_assets.py` (24 tests).
  Stage 2 landed: `agent/loop.py` — `AgentLoop.run()` and `inject_and_resume()`
  now accept `str | UserSubmission` (string input still works unchanged);
  images are stored via `ImageAssetStore(self.config.project_path)` and logged
  as `dagi_image` content parts (never base64 in the event log);
  `_build_request_messages()` now calls `materialize_messages()` so the
  provider only ever sees `image_url` data URLs; image-only first turns use
  the local `"image-conversation"` slug fallback instead of an LLM call or
  synthetic user text; `agent/session.py` `SessionTracker.record_user()`
  widened to `str | list`; `agent/session_events.py` `SESSION_FORMAT_VERSION`
  bumped 2 -> 3 (old runtimes reject v3 logs; `session_store.py` already read
  any version <= current, so v2 logs still load fine). Covered by
  `tests/test_loop_image_integration.py` (11 tests).
  Stage 3 landed (fork/resume/configuration): `agent/_loop_config.py` `AgentConfig`
  gained flat `supports_images` / `image_input_*` fields (None=unknown-permit,
  True=permit, False=block); `agent/config_loader.py` `_build_config_from_entry`
  now reads `supports_images` and a per-model `image_input:` block from
  `.dagi/config.yaml`; `agent/_model_switch.py` `handle_switch_model` gained a
  preflight (`_history_has_images`) that rejects a tier switch *before* any
  config/client mutation when the surface history contains `dagi_image` parts
  and the target tier's `supports_images` is explicitly `False`;
  `agent/_compaction.py` `compact()` now runs the reconstructed fork prefix
  through `materialize_messages()` before building the fork snapshot, so the
  compaction subprocess only ever sees data-URL images, never internal refs;
  `agent/history.py` gained a shared `_content_label()` helper used by
  `_derive_title()`, `build_turn_list()`, and `build_copyable_messages()` so
  image-only/mixed messages render as `"text [N images]"` instead of being
  stringified or skipped; `tools/compact/_tail_boundary.py` `estimate_tokens()`
  and `tui/utils.py` `_breakdown()` replaced the flat 200-token image
  placeholder with a per-image estimate (1024 tokens/image) added on top of
  real text-token counts. Covered by `tests/test_image_config_and_labels.py`
  (22 tests); `tests/test_tail_boundary.py` updated for the new per-image
  estimate.
  Stage 4 landed (PySide GUI composer): `pyside_gui/app.py`'s submission/dispatch
  logic (`_on_input_submitted`, `_dispatch_agent`, `_agent_work`,
  `_handle_special_command`) was extracted into `pyside_gui/_dispatch.py` as
  free functions taking the window as their first arg, keeping `app.py` under
  its 500-line cap (436 lines) while `DagiMainWindow` keeps thin wrapper
  methods for backward-compat test hooks. `pyside_gui/prompt_input.py`'s
  `PromptInput` is now a `QWidget` wrapping an inner `QPlainTextEdit`, an
  `_AttachmentStrip` of 64x64 thumbnails with per-image remove (X) buttons,
  and clipboard paste handling (`canInsertFromMimeData`/`insertFromMimeData`):
  image pixels (`QMimeData.hasImage()`) take precedence, then local file URLs
  with `.png`/`.jpg`/`.jpeg` extensions (whole batch rejected on any failure),
  else default text paste. Pasted/dropped images are decoded via `QImage`,
  encoded to PNG via `QImage.save()`/`QBuffer`, and validated against the same
  limits as `AgentConfig` defaults (max 4 images/message, 8 MiB/image, 24M
  px/image) before becoming an `ImageAttachment`; violations emit
  `attachment_error` (wired to the conversation's error bubble) and leave the
  existing draft untouched. `submitted` is now `Signal(object)` carrying a
  `UserSubmission` instead of `Signal(str)`. `_on_input_submitted` routes the
  full `UserSubmission` through to `AgentLoop.run()`/`inject_and_resume()`;
  pending-ask answers and slash commands reject image attachments (restoring
  the draft via `PromptInput.restore_draft()`) since neither accepts images;
  the conversation bubble shows `"text [N images]"` via a shared
  `_display_text()` helper. Heavy paste decode/encode stays on the GUI thread
  for v1 (TODO left in `prompt_input.py` to move it off-thread for large
  batches). Covered by `pyside_gui/tests/test_dispatch_and_submission.py` (8
  tests, Qt-free) plus `pyside_gui/tests/test_pending_ask.py` updated for the
  new module layout — full suite: 50 passed (up from 39 pre-stage-4), same 7
  pre-existing failures / 32 pre-existing errors (headless-Qt environment
  issues, confirmed present on the pre-stage-4 baseline too).
  Stage 5 landed (conversation-view rendering + error hardening):
  `pyside_gui/conversation.py` gained `append_user_message_with_images(text,
  image_paths)`, JSON-encoding the path list and delegating to a new JS
  function; `pyside_gui/resources/conversation.js` gained
  `appendUserMessageWithImages()`, which builds the same message-header/body
  markup as `appendMessage()` plus an `.image-gallery` of `<img
  class="sent-image-thumb">` tags — every path goes through `_escapeHtml()`
  before being placed in the DOM, so a crafted filename/path can't inject
  markup; `pyside_gui/resources/conversation.css` gained `.image-gallery`
  (flex row, wraps) and `.sent-image-thumb` (200x150 max, rounded corners,
  border, hover accent) rules. `pyside_gui/_dispatch.py` gained
  `_append_user_with_images(win, submission)`, used by both `dispatch_agent`
  (normal submit) and the inject-and-resume path in `on_input_submitted`: it
  resolves each attachment's file path via `ImageAssetStore.resolve_path()`
  (re-hashing the same bytes `AgentLoop._submission_content()` will hash),
  converts to a `file://` URL, and calls
  `append_user_message_with_images()`; on `AssetError` it shows
  `append_error("Couldn't load image preview: ...")` and falls back to the
  old `"text [N images]"` bubble instead of losing the message. `agent_work`
  now catches `AssetError` ahead of the general `Exception` handler and
  prefixes the surfaced message with `"Image error: "` for clarity (the
  general handler + `finally` block already restored input/showed
  `error_occurred` for every other failure path, confirmed by re-reading
  `_dispatch.py`). Text-only submissions are untouched — `append_user_message`
  and `appendMessage()` still handle them exactly as before. Verified via
  `conda run -n dagi python -m pytest pyside_gui/tests/test_dispatch_and_submission.py
  pyside_gui/tests/test_conversation_reasoning.py` (17 passed) plus `node
  --check conversation.js`; full `pyside_gui` suite still 50 passed / 7
  failed / 32 errors, same pre-existing headless-Qt baseline as stage 4.
  Remaining stage: end-to-end integration verification (stage 6).
