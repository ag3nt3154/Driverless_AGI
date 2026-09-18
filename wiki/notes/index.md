# Notes

Navigation to useful findings and open questions.

> Last updated: 2026-09-18

- Grep tool hardening (2026-09-18): **implemented**; `tools/grep/_grep.py` now excludes
  `.dagi/`, `__pycache__/`, `.git/`, `.mypy_cache/`, `.pytest_cache/`, `node_modules/`,
  `.tox/`, `.venv/`, `venv/` directories and binary extensions (`.pyc`, `.pyo`, `.pyd`,
  `.so`, `.dll`, `.exe`, `.bin`, `.whl`, `.egg`) from both ripgrep and Python-fallback paths.
  Tool description updated to mandate specific subdirectory paths (not `.`), name ripgrep
  explicitly, and forbid bash `findstr`/`grep` workarounds. `tools/output_filter.py`
  truncation message reordered: "refine your search" instruction now appears at the top
  of truncated results. 15 tests passing in `tests/test_grep_tool.py`.

- Wiki-index injection now sends only the wiki root path (2026-09-17): **implemented**;
  `_build_wiki_index_context` in `agent/_loop_helpers.py` previously read and concatenated
  every section `.index.md` file into a `[WIKI INDEX]` block on every turn — replaced with a
  one-line path pointer (`[WIKI]\nProject wiki root: <path>\n[END WIKI]`), since the model
  already has `wiki-query`/read tools to fetch specifics on demand. Verified via
  `tests/test_loop_helpers.py` + `tests/test_subagent_main.py` (47/47 passing); committed as
  `e2369be`. Surfaced two pre-existing, unrelated `test_agent_loop.py` failures and a `conda
  run` stdout-buffering gotcha while verifying — both logged in [errors](../errors/index.md).

- [Production review — 2026-09-15](production-review-2026-09-15.md): 19 actionable findings
  across subagents, the agent loop, PySide GUI, and session persistence; verdict not
  production-ready; recommendations remain unapproved.

- [Large-file reader investigation](large-file-reader-2026-09-09.md): plan-only findings
  that informed the approved redesign below.
- [Large-file reader plan (full)](large-file-reader-plan-2026-09-09.md): complete
  redesign specification with six review amendments (A1–A6); **approved and implemented
  2026-09-09** — 6 subtasks, 100 tests, all passing.
- [Image input research and proposal](image-input-proposal-2026-09-13.md): research and detailed
  implementation handoff recorded; design remains **unapproved**; no implementation or endpoint
  smoke test was performed.

- [Code review — 2026-09-08](2026-09-08_CODE_REVIEW.md): 37 findings across agent/,
  tools/, pyside_gui/, root scripts. 3 critical (cross-thread race, double JSON encoding,
  dead stub with latent ImportError), 12 dead-code, 9 bloat, 13 improvements.
- [Broad repository review](broad-review-2026-09-06.md): six unfixed scheduler, session,
  Telegram, and CLI findings; reproductions and verification limits.
- [Dependency and housekeeping review](housekeeping-2026-09-06.md): dependency split,
  conservative Markdown cleanup, retained dead-code candidates, and verification limits.

- [/revise-history open questions](revise-history-open-questions.md): unresolved behaviour
  at the `/hist` seed boundary — defer until after initial implementation.

- [Approved project wiki contract](wiki-contract.md): storage, delegation, lifecycle,
  failure handling, and refresh decisions approved 2026-09-05; implementation complete 2026-09-05.
- [Project TODOs](project-todos.md): open and completed tasks.
- [PySide thinking display](pyside-thinking-display-2026-09-12.md): completed behavior and
  verification details for the three-line streaming preview and final Markdown rendering.
- Slash-command autocomplete (2026-09-17): **implemented**; `SlashCompleterPopup` wired into
  `PromptInput`; 40 tests passing. See [architecture](../architecture.md) for details.
- Codex skill lifecycle finding (2026-09-06) is recorded in [wiki contract](wiki-contract.md)
  and [workflows](../workflows.md); completion is limited to skill files and lifecycle docs.
- Codex completion verification (2026-09-06): focused dagi wiki-delegation tests passed, 59
  tests, using `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `--noconftest`,
  `-p no:cacheprovider`, and `--basetemp=.dagi/test-tmp-codex`. Model-backed Codex scenarios
  remain untested, and instruction-only file confinement remains a known limitation.

[Project wiki](../index.md)
