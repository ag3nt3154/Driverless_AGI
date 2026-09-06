# Dependency and housekeeping review

> Completed: 2026-09-06; broader cleanup candidates remain open.

The user requested Markdown cleanup, separate core/GUI/tools requirements, and dead-code review.
With no reply to the optional document-retention question, cleanup used conservative scope.

## Implemented scope

- Removed only `.dagi/handoffs/explore_files_557e78bf.md`: an obsolete generated architecture
  inventory claiming removed plan sentinels, Git tools, in-process subagents, and five test files.
- Retained reports, dated TODOs, design documents with unresolved items, nested projects,
  benchmark fixtures, active prompts, and skills.
- After the user's explicit correction, requirements files contain literal `package==version`
  entries split from the original HEAD `requirements.txt`, not editable extras wrappers.
  All 166 original pins are preserved exactly once: core (20), GUI (19), TUI (8), tools (16),
  PDF (77), legacy (18), and dev (8). No packages were silently dropped or versions changed.
- GUI also includes `-r requirements-tui.txt` because GUI imports TUI. The aggregate
  `requirements.txt` includes core, GUI, tools, PDF, legacy, and dev; TUI is included transitively.
- `requirements-pdf.txt` preserves the original document/ML pins. The unchanged
  `services/doc_converter/environment.yml` remains recommended for complete converter
  server/system setup. `requirements-legacy.txt` preserves the old LangChain stack, unused by core.
- `pyproject.toml` retains the prior direct-dependency extras but is no longer the source of
  pinned requirement lists. The original requirements omitted ddgs/crawl4ai; the optional web
  extra remains available separately.
- History: the first implementation replaced the original pins with editable extras wrappers
  and omitted legacy/transitive/PDF/ML packages. The user clarified that separate pip-installable
  documents preserving the original entries were required; the pinned split supersedes that design.
- Root `environment.yml` is now a minimal Python 3.14 core conda recipe referencing
  `requirements-core.txt`, run from the repository root.
- Replaced invalid `setuptools.backends.legacy:build` with `setuptools.build_meta` and
  explicit package discovery for editable installs. Corrected README installation/dependency
  documentation and AGENTS date/install commands, preserving behavioral content.
- In `agent/session.py`, removed unused `dataclasses.field` and dead `cost_str`/`tools_str`
  formatting after the `session_end` write. Totals and persistence are unchanged.

## Review candidates retained

Initial Ruff F401/F841 review reported 36 findings; exports and availability checks mean these
are not all dead code. AST/reference review found no active callers for the following, but
dynamic/external clients have not been ruled out, so none were deleted:

| Candidate | Review context |
|-----------|----------------|
| `agent/sub_agent.py:19` `SubAgentRunner` | Legacy in-process runner; active API is `tools/subagent_api.py`. |
| `pyside_gui/overlays.py:68` `AskUserDialog` | App imports `CopyPicker`; questions use `app._on_ask_user` and bridge. |
| `agent/skills.py:136` `format_skills_for_prompt` | Active formatting is in `agent/_system_prompt.py`. |
| `agent/config_loader.py:57` `get_model_display_name` | TUI comment says root-only configuration misses overrides. |
| `tools/workflow/_workflow.py:68` `list_workflows` | Exported public wrapper; retained. |

`WebResearchTool` and `EmoteTool` exports must not be classified as dead from name scans alone.

## Verification and limits

- Before the requirements correction, 103 tests passed across `test_session_tracker.py`, `test_agent_loop.py`, `test_read_tool.py`,
  and `test_config_loader.py`, using dagi Python, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`,
  `--noconftest -p no:cacheprovider --basetemp=.dagi/test-tmp-housekeeping`.
  The first run without workspace basetemp had 49 passes and 54 setup permission errors;
  the rerun resolved these. Temporary artifacts were removed.
- Historical editable-wrapper verification: pip dry runs with `--no-deps --no-build-isolation` succeeded for core and all four optional
  requirement manifests combined. This checks metadata only: no fresh-environment installation
  or network dependency resolution was performed. This does not verify the corrected pinned files.
- The source code is unchanged by the requirements correction; the 103 source tests still apply.
- Pip's requirements parser verified the corrected aggregate yields exactly the original 166
  entries, all `==` pins, without duplicates or loss. Standalone core has 20 entries and excludes
  UI/PDF/LangChain. No installation or network resolution was performed; `git diff --check` passed.
- README installation instructions were corrected; AGENTS explicitly uses `requirements-core.txt`.
- A core-only smoke test used a MetaPathFinder in dagi Python to block PySide6, textual, typer,
  langchain, langchain_openai, docling, torch, fitz, bs4, ddgs, crawl4ai, telegram, psutil,
  and win11toast. It imported `main`, `AgentLoop`, and `scheduler.runner`, and created a registry
  with 16 registered tools.
- Ruff F401/F841 passed for changed `agent/session.py`; `git diff --check` passed.
- No live GUI/PDF/web checks, commit, branch creation, or network installation occurred.

[Notes](index.md) | [Workflows](../workflows.md) | [Project wiki](../index.md)
