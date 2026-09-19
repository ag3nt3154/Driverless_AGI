# Project Wiki

Project knowledge and navigation.

> Last updated: 2026-09-19

- [Production review — 2026-09-15](notes/production-review-2026-09-15.md): 19 actionable
  findings; verdict **not production-ready**; recommendations remain unapproved.

- [Architecture](architecture.md): entry points, agent loop, subagent system, tool registry.
- [Workflows](workflows.md): delivery, planning, wiki lifecycle, testing, model switching.
- [Business context](business-context.md): purpose, users, and constraints.
- [Decisions](decisions/index.md): choices and their rationale.
- [Errors](errors/index.md): observed issues and verified fixes.
- [Notes](notes/index.md): useful findings, open questions, and project todos.

- [GUI context duplication audit](notes/gui-context-duplication-2026-09-18.md#follow-up-audit--2026-09-18):
  six open context and compaction findings confirmed offline on 2026-09-18; no fixes approved or
  implemented by that audit.

## Reviews

- [Large-file reader investigation](notes/large-file-reader-2026-09-09.md): completed
  plan-only investigation; led to approved redesign below.
- [Large-file reader plan](notes/large-file-reader-plan-2026-09-09.md):
  approved and **fully implemented** 2026-09-09. Size-based trigger, deterministic
  controller, chunking adapter, subprocess integration — 100 tests passing.

- [Broad repository review](notes/broad-review-2026-09-06.md): completed 2026-09-06
  against clean `main` at `707b573`; six actionable findings remain unfixed.
- [Image input research and proposal](notes/image-input-proposal-2026-09-13.md): research and detailed
  implementation handoff recorded; proposed design is **unapproved** and no implementation or
  endpoint test was performed.

## Implemented features

- **Garbled loop recovery** (2026-09-18): Detects consecutive empty-content model
  responses, strips degenerate turns via `revise_last_step()`, and triggers full
  context compaction. Shows `PROCESS compacting` in PySide sidebar during recovery.

- **Slash-command autocomplete** (2026-09-17): `SlashCompleterPopup` in
  `pyside_gui/slash_completer.py`; wired into `PromptInput` and `_Editor`. Typing `/`
  shows a filtered popup of all commands, skills, and workflows. Tab/Enter accepts,
  Up/Down navigates, Escape dismisses. Completions refresh automatically on `/wd`.
  40 tests in `tests/pyside_gui/test_slash_completer.py`.

## Approved designs

- [Project wiki contract](notes/wiki-contract.md): decisions approved 2026-09-05;
  implementation complete 2026-09-05.
