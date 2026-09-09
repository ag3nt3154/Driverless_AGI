# Project Wiki

Project knowledge and navigation.

> Last updated: 2026-09-09

- [Architecture](architecture.md): entry points, agent loop, subagent system, tool registry.
- [Workflows](workflows.md): delivery, planning, wiki lifecycle, testing, model switching.
- [Business context](business-context.md): purpose, users, and constraints.
- [Decisions](decisions/index.md): choices and their rationale.
- [Errors](errors/index.md): observed issues and verified fixes.
- [Notes](notes/index.md): useful findings, open questions, and project todos.

## Reviews

- [Large-file reader investigation](notes/large-file-reader-2026-09-09.md): completed
  plan-only investigation; led to approved redesign below.
- [Large-file reader plan](notes/large-file-reader-plan-2026-09-09.md):
  approved and **fully implemented** 2026-09-09. Size-based trigger, deterministic
  controller, chunking adapter, subprocess integration — 100 tests passing.

- [Broad repository review](notes/broad-review-2026-09-06.md): completed 2026-09-06
  against clean `main` at `707b573`; six actionable findings remain unfixed.

## Approved designs

- [Project wiki contract](notes/wiki-contract.md): decisions approved 2026-09-05;
  implementation complete 2026-09-05.
