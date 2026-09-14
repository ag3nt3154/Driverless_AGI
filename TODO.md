# TODO

## In progress

- **Image input, stage 1 of 6 done** (see `docs/image-input-implementation-plan.md`).
  Landed: `agent/user_input.py` (Qt-free `ImageAttachment`/`UserSubmission` value
  objects) and `agent/image_assets.py` (`ImageRef`, `ImageAssetStore`,
  `materialize_messages` — content-addressed store under `.dagi/attachments/`,
  atomic writes, hash/size validation, path-traversal guards). Covered by
  `tests/test_image_assets.py` (24 tests).
  Remaining stages: loop/persistence wiring, fork/resume/config, GUI composer,
  sent-image rendering, integration verification.
