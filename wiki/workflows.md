# Workflows

Current development and execution flows.

> Last updated: 2026-09-06

## Primary Execution Flow

1. An entry point starts `AgentLoop` with configuration, tools, session state, and UI callbacks.
2. `AgentLoop` assembles stable instructions plus dynamic context, calls the provider, and
   dispatches tool requests through `ToolRegistry`.
3. `SessionTracker` and `SessionLog` persist conversation, usage, and subagent branch events.
4. Subagents run through `tools/subagent_api.py`; inherited children reuse the captured parent
   request prefix and finish through `write_handoff`.
5. TUI, PySide, Telegram, and CLI entry points translate the same callbacks and agent state.

## Delivery Workflow

Primary entry point: `/deliver` (`.dagi/skills/deliver/SKILL.md`).

```
/deliver → wiki-query (once, overall task)
         → grilling (if intent unresolved)
         → /plan → plan review → wiki-add (approved decisions)
         → per-task: worker → reviewer → update_task_status
         → integrated verification + final review
         → wiki-add (completion evidence)
         → set_active_plan(null) detach
```

- `/plan` (`.dagi/skills/plan/SKILL.md`): codebase exploration, spec, plan approval,
  `wiki-add` of approved decisions, `set_active_plan`.
- `/dagi-execute` (`.dagi/skills/dagi-execute/SKILL.md`): resumes interrupted deliveries
  from the first pending subtask; checks wiki-add evidence before continuing.
- Worker outcomes: `READY_FOR_REVIEW` | `ESCALATE`.
- Reviewer outcomes: `PASS` | `ESCALATE`. Workers return `Wiki requests` in handoffs for main.

## Planning

- Plan scaffold: `create_plan` tool → `.dagi/plans/plan_{timestamp}/plan.md`.
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

Triggered automatically when context approaches the limit. The `compact` subagent inherits the
parent's warm KV-cache prefix via retroactive branching. Compaction generation counter
increments on success. Surface-aware step collection skips already-summarized steps.

## Model Switching

- `switch_model(tier="plan")` → advanced model for planning.
- `switch_model(tier="default")` → back to default model after planning.
- `switch_model(tier="worker")` → cheaper model for subagents.

## Testing

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
