# TODO

## In progress

- **Image input, stage 3 of 6 done** (see `docs/image-input-implementation-plan.md`).
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
  Remaining stages: GUI composer, sent-image rendering, integration
  verification.
