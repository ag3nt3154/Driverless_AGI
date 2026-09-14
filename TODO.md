# TODO

## In progress

- **Image input, stage 2 of 6 done** (see `docs/image-input-implementation-plan.md`).
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
  Remaining stages: fork/resume/config, GUI composer, sent-image rendering,
  integration verification.
