# TODO

## In progress

- **Slash-command autocomplete (Tasks 2+)** — `completions()` method added to
  `SlashCommandHandler` (Task 1 complete); popup widget and integration with the
  PySide6 prompt input still pending.

- **Production review (R5, R8, R11, R17)** — remaining deferred findings from
  `wiki/notes/production-review-2026-09-15.md`. R5 (session filename
  collisions) and R8 (pipe subagent prompt loss) deferred pending design
  decisions; R11 (interrupted restore from events) deferred for complexity;
  R17 (orderly GUI shutdown) deferred — needs design for worker cancellation,
  process-tree cleanup, and state persistence.

## Completed

- **Production review fixes (R1–R4, R6–R7, R9–R10, R12–R16, R18–R19)** —
  fifteen findings from `wiki/notes/production-review-2026-09-15.md` fixed:
  - R1: Compact fork now resolves credentials from the parent's actual model,
    not the default, preventing cross-provider key/endpoint mismatch.
  - R2: All model-output markdown render paths use `allow_html=False`,
    preventing injected HTML/event attributes from executing in the
    conversation page.
  - R3: Session restore and title derivation now use the last `session_end`
    record instead of the first, recovering all turns in a multi-turn session.
  - R4: GUI submissions carry the existing `SessionLog` to the new
    `AgentLoop` instead of creating a fresh one, keeping event sequence
    numbers monotonic across turns.
  - R6: Tool dispatch checks pause state before each tool execution,
    cancelling remaining tools instead of running them after the user pauses.
  - R7: A nonzero child exit code now always produces an error result, even
    when a handoff file exists on disk from a prior failed validation attempt.
  - R9: When the model groups `write_handoff` with other tool calls, the
    handoff is deferred and executed last so no calls are orphaned.
  - R10: Session restore is blocked while a worker thread is running,
    preventing the old worker from contaminating the restored view.
  - R12: Idle GUI compaction wraps `compact()` in a maintenance turn so
    the CONTEXT_COMPACTION surface event doesn't violate the open-turn
    invariant.
  - R13: Malformed tool-argument repair now re-projects the surface cache
    entry so the stale deep copy doesn't send broken JSON to the API.
  - R14: Bridge emits `ask_user_expired` on question timeout, clearing
    the pending-ask sink so the next user input isn't silently swallowed.
  - R15: `/clear` now resets pending restored history and affect state so
    the next task starts fresh.
  - R16: Observer callback and log-write failures inside the child stdout
    drain loop are individually caught so a throwing callback can't block
    the pipe.
  - R18: The stream deduplication flag resets after suppressing one
    duplicate so post-stream diagnostic messages still appear.
  - R19: Preflight work (wiki context, submission content, slug generation)
    is inside the try/finally that closes the turn, so a preflight failure
    can't leave a turn permanently open.


- **Reader subagent crash fixed** — `_run_with_job` in
  `tools/read/_reader_controller.py` passed the selection's parent directory as
  the positional `model_id` argument to `resolve_model_config` instead of as
  `project_path`, causing an immediate crash. Additionally, `_build_runtime`
  never set `handoff_tool` or `callbacks` on the `ReaderRuntime`, so the
  subprocess would also fail when writing the handoff. Both bugs are fixed;
  stale test assertions in `test_read_tool.py` updated to match the current
  delegation flow ("`Delegated to reader`" instead of the old
  "`Delegated to read_large_text`", `reader_job_spec.query` instead of
  `custom_instructions`).


- **Wiki handoff validation made case-tolerant** — `_validate_handoff` in
  `tools/_wiki_tools.py` now normalises heading casing before matching
  (e.g. "Wiki Sources" → "Wiki sources"), accepts `no results` as well as
  `no_results` for query outcomes, and tolerates trailing periods on outcome
  and failure-details values. The split regex also accepts a missing trailing
  newline after the last heading. Both wiki-query and wiki-add SKILL.md child
  protocols were tightened: handoff format is now shown in a fenced code block
  with explicit instructions against preamble text and extra sections.

- **Subagents now inherit the main agent's context settings** — previously,
  `_apply_worker_config` and `_apply_advanced_config` in `tools/subagent_main.py`
  (and the equivalent in `agent/sub_agent.py`) replaced `context_window`,
  `reserve_tokens`, and `keep_recent_tokens` with the worker/advanced model's own
  values. Now only LLM-identity fields (model, base_url, api_key, thinking) come
  from the tier-specific config; context budget always stays from the main agent's
  `.dagi/config.yaml` top-level settings.

- **Malformed tool-call arguments no longer crash the agent loop** — when a model
  produces invalid JSON in tool-call arguments (e.g. unclosed `"` or `{}` in markdown
  content for `write_handoff`), the dispatch code already caught the `JSONDecodeError`
  and returned an error to the model, but the raw malformed string remained in the
  conversation history. On the next API call the provider rejected it with a 400,
  which was not retried and crashed the loop. Fix: `_tool_dispatch.py` now wraps
  the malformed string in valid JSON (`{"_malformed": "..."}`) and patches both the
  `TOOL_CALL` and `ASSISTANT_MESSAGE` log events before re-syncing messages.

- **Image input — all 6 stages complete** (see `docs/image-input-implementation-plan.md`).
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
  Stage 6 landed (integration verification and documentation): extended the
  four Stage 1-4 test files with the Section 10 gaps — wire payload tests
  (`tests/test_loop_image_integration.py`: exact PNG byte round-trip through
  the outgoing data URL, MIME-type correctness for PNG/JPEG, text-part-before-
  image-part ordering, multiple distinct images in one message, image-only
  messages, and text-only messages staying a plain string); a persistence
  round-trip test (store an image, seed a fresh `AgentLoop` from the prior
  loop's messages the way GUI resume does, materialize, and get back
  byte-identical PNG data with the original `ImageAttachment`/`UserSubmission`
  out of scope — modeling "source file deleted, clipboard cleared"); asset
  store gap tests (`tests/test_image_assets.py`: concurrent identical writes
  from 8 threads never corrupt the stored file — tolerating, per the module's
  own documented deferred-concurrency guarantee, that a losing writer may see
  a transient `PermissionError` on Windows `os.replace`; a symlinked asset
  path is rejected by `load()`, skipped if the sandbox disallows creating
  symlinks); history-label gap tests
  (`tests/test_image_config_and_labels.py`: image-only/mixed labels across
  `_content_label`, `_derive_title`, `build_turn_list`, and
  `build_copyable_messages` are asserted to never contain `{`/`}` or
  `sha256` — i.e. never a stringified dict or raw reference); and GUI routing
  tests (`pyside_gui/tests/test_dispatch_and_submission.py`:
  `_append_user_with_images` with a fake `win`/`_conversation`/`_config`
  verifying it calls `ImageAssetStore.store()` and produces `file:///` URLs,
  falls back to the error bubble + `"text [N images]"` text bubble on
  `AssetError` without losing the message, and leaves the text-only path
  byte-for-byte unchanged with no `.dagi/` directory created). Full targeted
  run: `conda run -n dagi python -m pytest tests/test_image_assets.py
  tests/test_loop_image_integration.py tests/test_image_config_and_labels.py
  pyside_gui/tests/test_dispatch_and_submission.py --noconftest -v` — 81
  passed, 1 skipped (symlink test, sandbox-dependent). README.md gained an
  "Image Input (PySide GUI)" section documenting the feature and
  `.dagi/config.yaml` `image_input:` knobs.
  **Not yet done:** the opt-in live endpoint smoke test against a real
  vision-capable model (plan Section 10's last item) has not been run — it
  requires a configured vision-capable model's credentials, which are not
  available in this environment. All automated verification is complete;
  only that manual/live step remains unrun.
