# Approved Project Wiki Contract

Approved storage, delegation, and lifecycle decisions for the project wiki.

> Approved: 2026-09-05
> Last updated: 2026-09-06
> Status: Codex skill and lifecycle implementation complete 2026-09-06; dagi-specific
> D1/D2/D3/O1/O2 remain complete. Codex model-backed testing and instruction-only
> confinement verification remain outstanding; no end-to-end model scenario is claimed.

## Storage and authority

- Keep the project-root `wiki/` tracked in Git on the current branch.
- The wiki and compact `AGENTS.md` are authoritative. `README.md` is downstream.
- Only the main agent updates `AGENTS.md`, retaining project identity, standing rules,
  essential commands, and wiki lifecycle instructions.
- Initial layout: `index.md`, `architecture.md`, `workflows.md`, `business-context.md`,
  `decisions/index.md`, `errors/index.md`, and `notes/index.md`.
- `/init` uses pure code to create only missing placeholder documents and folders.
  Preserve all existing files, including empty files. Existing-document migration is separate.
- Execution plans remain outside the wiki: dagi uses `.dagi/plans`; Codex may use an
  arbitrary location. Saved decisions do not require the exact execution-plan link.
- Roadmap design is deferred. Relocate the existing TODO unchanged into the wiki as
  an interim measure.

## Main-agent lifecycle

- Before each overall substantive task, the main agent delegates a wiki query.
- After overall plan approval, the main agent delegates an add of essential approved
  decisions and user choices, selected by the main agent.
- After full plan completion, the main agent delegates an add recording actual
  implemented behavior and completion status.
- Discretionary queries and adds are encouraged for substantial questions, bugs,
  fixes, and findings.
- The main agent stays free of wiki traversal context: query and add children traverse
  the wiki and return handoffs.
- No subagent nesting. Workers request wiki operations in their handoffs.
- Personal memory remains separate and is used only on explicit user requests;
  replace old automatic personal-memory triggers.

## Delegation and handoff contract

Separate dagi and Codex skill versions share the same storage and handoff contract.
Query and add children are restricted to wiki traversal and their native handoff.

- Query handoff: outcome (`success`, `no_results`, or `error`), findings, sources,
  conflicts, gaps, and failure details.
- Add handoff: outcome (`success` or `error`), paths, change summary, conflicts,
  partial writes, and failure details.
- An initialized empty wiki returns `no_results`, which permits work to proceed.
- Query failure: retry once, then block the task.
- Approval-add failure: retry once, then block implementation.
- Completion-add failure: retry once; unresolved failure leaves the workflow incomplete.
- Retries after partial writes must avoid duplicate entries.
- No asynchronous protection for now. Lifecycle requirements are skill instructions
  only, with no runtime transition gates.

## Codex skill lifecycle finding (2026-09-06)

- Installed Codex project skills are `C:/Users/alexr/.codex/skills/wiki-query/SKILL.md`,
  `wiki-add/SKILL.md`, `wiki-refresh/SKILL.md`, and `update-project-context`.
- Codex `wiki-query` is a read-only subagent protocol; `wiki-add` delegates explicit
  main-agent-selected points; `wiki-refresh` is explicit and main-agent-only.
- Project instructions require `wiki-query` before overall substantive tasks, `wiki-add`
  after plan approval and after full completion, no nested subagents, and personal memory
  only on explicit user request.
- Dagi wiki-delegation tests passed: 59 tests with
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `--noconftest`, `-p no:cacheprovider`, and
  `--basetemp=.dagi/test-tmp-codex`.
- Codex skill installation has no automated model-backed test yet. Instruction-only file
  confinement remains a known limit; this entry does not claim migration or a full
  end-to-end model scenario.

## Conflicts, refresh, and evidence

- Preserve contradictory accounts as dated, explicitly conflicted findings. Queries
  return both accounts instead of choosing one.
- Wiki refresh is explicit and performed directly by the main agent. It investigates
  code and project evidence and asks the user when needed. There is no automatic refresh.
- Bug entries distinguish symptoms, suspected causes, confirmed causes, and verified fixes.

[Notes](index.md) | [Decisions](../decisions/index.md) | [Project wiki](../index.md)
