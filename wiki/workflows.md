# Workflows

Current development and execution flows.

> Last updated: 2026-09-24

> The 2026-09-20 review and implementation result supersede the earlier ownership and routing
> summary for the approved checklist points 1–2. Remaining recommendations are still open. See
> [Workflow review — 2026-09-20](notes/workflow-review-2026-09-20.md).

## Primary Execution Flow

1. An entry point starts `AgentLoop` with configuration, tools, session state, and UI callbacks.
2. `AgentLoop` assembles stable instructions plus dynamic context, calls the provider, and
   dispatches tool requests through `ToolRegistry`.
3. `SessionTracker` and `SessionLog` persist conversation, usage, and subagent branch events.
4. Subagents run through `tools/subagent_api.py`; inherited children reuse the captured parent
   request prefix and finish through `write_handoff`.
5. TUI, PySide, Telegram, and CLI entry points translate the same callbacks and agent state.

## Delivery Workflow

Lifecycle owner: `enter-workflow` (`.dagi/skills/enter-workflow/SKILL.md`); delivery is the
owner-routed `/deliver` stage (`.dagi/skills/deliver/SKILL.md`).

`enter-workflow` is the sole lifecycle owner for stages, approval, active-plan state, and closure.
The owner preserves the wiki-query gate, approval wiki-add, independent plan review, completion
wiki-add/update-context, and closure detach. The owner routes planning, specification, writing,
review, approval, and delivery stages; those skills return control instead of launching later
stages. Standalone `/deliver` redirects to the owner once; an owner-invoked deliver stage does
not redirect.

```
enter-workflow → explore/grill → approval → plan/spec → deliver
              → per-task: worker → reviewer → update_task_status
              → integrated verification + final review
              → do-tdd evidence → merging-git-branch (merge or keep)
              → wiki-add (completion evidence) → detach before final response
```

Blockers requiring a plan or scope change return to `enter-workflow`. The approved implementation
is at the prompt and skill-instruction level. `deliver` loads the lowercase runtime skill
`do-tdd` and sends its full instructions to workers through `custom_instructions`, including
repair guidance because workers cannot load skills themselves. Workers return red/green/refactor
evidence and limitations without permission expansion; the bounded main implementer also receives
the TDD instructions. If no task branch exists, no merge offer is made. `enter-workflow` captures
the parent before branching and carries it into plan Notes; `write-plan` links both stages.

After successful delivery verification, `merging-git-branch` checks current evidence and uses
`no_timeout` `ask_user` for only an explicitly named local target or keep-as-is. It never pushes,
creates a PR, or cleans up automatically. The owner records merged/kept/blocked, writes wiki and
context completion records, and detaches only after success; blocked work remains attached and
keep-as-is is valid completion. Closure documentation targets the appropriate checkout and reports
uncommitted docs without auto-committing. No runtime Python changes, commit, branch, or merge were
made. Point 3 entry/resume guidance is now implemented at the instruction level: the owner
classifies new versus continuing requests, checks active-plan evidence before plan actions,
preserves checkpoints through compaction, resumes from accepted evidence, and blocks mutations on
unknown or stale evidence. Merge interruption checks actual Git state and keeps an explained branch
mismatch associated through closure. README and AGENTS checklist guidance was updated; existing
uncommitted TDD and merge work was preserved. See the [point 3 completion](notes/workflow-review-2026-09-20.md#checklist-point-3-completion--2026-09-24)
for scope and verification limits; known plan-format gaps remain open.

- `/dagi-execute` (`.dagi/skills/dagi-execute/SKILL.md`): resumes interrupted deliveries
  from the first pending subtask; checks wiki-add evidence before continuing.
- Worker outcomes: `READY_FOR_REVIEW` | `ESCALATE`.
- Reviewer outcomes: `PASS` | `ESCALATE`. Workers return `Wiki requests` in handoffs for main.

The former `/plan` adapter was removed after the user correction that planning is superseded by
the `write-plan` skill. `write-plan` remains a standalone artifact-only writer; `enter-workflow`
owns approval and the transition into delivery. This supersedes the earlier adapter-preservation
summary while retaining the implementation history in the workflow review note.

## Planning

- Plans are written under `wiki/plans/YYYY-MM-DD-<task-name-slug>/plan.md` using
  the `write-plan` skill.
- Plan-format and artifact-location consistency remain open follow-up work.
- Active plan: tracked at `.dagi/session-state/<thread_id>/active-plan.json`.
- `handle_all_tasks_resolved` does NOT clear the association — plan stays for final verification.
- Explicit detach: `set_active_plan(null)` after delivery accepted.

## Wiki Lifecycle

- Before overall substantive tasks: main agent calls `wiki_query`.
- After plan approval: main agent calls `wiki_add` with approved decisions/user choices.
- After full completion and verification: main agent calls `wiki_add` with results/completion.
- Workers return `Wiki requests` in handoffs; only main agent delegates wiki operations.
- `wiki-refresh` is explicit, main-agent-only (`.dagi/skills/wiki-refresh/SKILL.md`).

Codex project skills mirror this lifecycle through installed files at
`C:/Users/alexr/.codex/skills/wiki-query/SKILL.md`, `wiki-add/SKILL.md`,
`wiki-refresh/SKILL.md`, and `update-project-context`: query is read-only, add accepts
only points selected by the main agent, and refresh remains explicit/main-agent-only.
The Codex installation is verified at the instruction and lifecycle-document level;
there is no automated model-backed skill test yet, and instruction-only file confinement
is still a known limit.

## Context Compaction

Triggered automatically when context approaches the limit. Surface-aware step collection skips
already-summarized steps. The approved 2026-09-23 policy is implemented and verified: compaction
resolves the configured project `default_model`, endpoint, credentials, and options. On error,
it removes exactly the selected chunk from active model context while retaining the recent tail
and raw append-only log, with a small omission marker; unchanged surface generation and the exact
original span are validated before summary or fallback replacement. Preparation/invocation
exceptions, non-OK or timeout results, and empty summaries use the fallback once after selection;
no candidate remains a no-op. Recovery `summarize_all` is covered. See the [BookWriter compaction
report](notes/gui-context-duplication-2026-09-18.md#explicit-compaction-policy-approval-and-verified-completion--2026-09-23).

## Model Switching

- `switch_model(tier="plan")` → advanced model for planning.
- `switch_model(tier="default")` → back to default model after planning.
- `switch_model(tier="worker")` → cheaper model for subagents.

## Dependency installation

Use the `dagi` Python environment and run installation from the repository root:
`python -m pip install -r requirements-core.txt` installs core alone. Add other feature files
with multiple `-r` arguments: GUI, TUI, tools, PDF, legacy, or dev. GUI includes TUI because
GUI imports it. `requirements.txt` is the full aggregate, including TUI transitively through GUI.

The seven files preserve all 166 original `package==version` entries exactly once: core (20),
GUI (19), TUI (8), tools (16), PDF (77), legacy (18), and dev (8). PDF retains document/ML pins;
legacy retains the old LangChain stack, unused by core. The unchanged converter service
`environment.yml` remains recommended for complete converter server/system setup.
`pyproject.toml` retains direct-dependency extras separately; the optional web extra provides
originally omitted ddgs/crawl4ai. Root `environment.yml` references `requirements-core.txt`.
The earlier editable-extras wrappers were superseded by this split after user correction.
See the [housekeeping review](notes/housekeeping-2026-09-06.md) for history and parser verification;
no installation or network resolution was performed for the corrected files.

## Testing

The 2026-09-24 verification loaded the five relevant skills through the actual `dagi` loader and
tool, and mocked worker dispatch preserved the full loaded TDD instructions. All 32 tests in
`tests/test_subagent_tools_new.py` passed with an isolated writable basetemp after four initial
temp-fixture permission errors were resolved by changing only the basetemp. Generic merge
validation and `git diff --check` passed. No live model or end-to-end merge execution occurred.

Run isolated tests (avoids RAM watchdog and pytest-qt DLL issue):
```
python.exe -m pytest --noconftest -p "no:pytest-qt" tests/<file>.py -v
```

For the full suite with the RAM watchdog active:
```
conda run -n dagi python -m pytest tests/ -v
```

Note: full suite requires PySide6 DLL path to be set (handled by `tests/conftest.py`).
The pytest-qt entry point name is `pytest-qt`, not `qt`.

[Project wiki](index.md)
