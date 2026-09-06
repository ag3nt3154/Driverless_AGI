# Notes

Navigation to useful findings and open questions.

> Last updated: 2026-09-06

- [Broad repository review](broad-review-2026-09-06.md): six unfixed scheduler, session,
  Telegram, and CLI findings; reproductions and verification limits.
- [Dependency and housekeeping review](housekeeping-2026-09-06.md): dependency split,
  conservative Markdown cleanup, retained dead-code candidates, and verification limits.

- [Approved project wiki contract](wiki-contract.md): storage, delegation, lifecycle,
  failure handling, and refresh decisions approved 2026-09-05; implementation complete 2026-09-05.
- [Project TODOs](project-todos.md): open and completed tasks; relocated from TODO.md 2026-09-05.
- Codex skill lifecycle finding (2026-09-06) is recorded in [wiki contract](wiki-contract.md)
  and [workflows](../workflows.md); completion is limited to skill files and lifecycle docs.
- Codex completion verification (2026-09-06): focused dagi wiki-delegation tests passed, 59
  tests, using `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `--noconftest`,
  `-p no:cacheprovider`, and `--basetemp=.dagi/test-tmp-codex`. Model-backed Codex scenarios
  remain untested, and instruction-only file confinement remains a known limitation.

[Project wiki](../index.md)
