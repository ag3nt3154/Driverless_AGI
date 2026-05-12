# Project: Driverless_AGI (dagi)

> **Last updated:** 2026-05-12
> **Update after:** any task that changes the codebase, adds tools/skills, changes dependencies, or resolves an error. Use `edit` for incremental updates only. Maintain at most 5 recent changes.

## Description

dagi is a self-contained agentic coding assistant engine. It runs an agentic loop that can read, write, edit, and execute code across a local project. It is also capable of self-improvement — extending its own tools, skills, and prompts.

## Objectives

- Provide a reliable, extensible agentic coding loop compatible with any OpenAI-compatible LLM endpoint.
- Support project-local customisation via `.dagi/` scaffolding (tools, skills, workflows, agents.md).
- Enable self-improvement through the `review-session` skill and `improve-yourself` workflow.

## Directory Structure

```
Driverless_AGI/
├── agent/              # Core engine — loop, registry, tools, prompts, session tracking
├── tools/              # Built-in tools (compact, explore_files, web_research, spawn_subagent, etc.)
├── scripts/            # Utility scripts (dagi_freeze, build_api_tools, etc.)
├── projects/           # Experimental sub-projects (prompt_opt, etc.)
├── .dagi/
│   ├── agents.md       # This file — dagi engine context loaded every session
│   ├── prompts/
│   │   ├── main/       # main_system.md — primary agent system prompt
│   │   ├── subagents/  # explore_files, web_research, worker, review prompts
│   │   └── compact/    # compact_system, compact_user prompts
│   ├── skills/         # Built-in skills (memory-add, memory-ingest, review-session, etc.)
│   ├── workflow/       # Built-in workflows (improve-yourself)
│   ├── plans/          # Generated plan documents
│   ├── logs/           # Session JSONL logs
│   └── self-review/    # Session review reports
├── soul.md             # Agent identity and personality
├── cli.py              # Interactive CLI entry point
├── README.md           # Full documentation
└── config.yaml         # Runtime config (gitignored)
```

## Environment

- **Language:** Python 3.11+
- **Runtime / virtual env:** `conda` — environment name `dagi`
- **Install dependencies:** `conda run -n dagi pip install -e .`
- **Run command:** `conda run -n dagi python cli.py` or activate env and run `python cli.py`
- **Config:** `config.yaml` (gitignored) — sets model, base_url, api_key, max_iterations

## Known Issues & Resolutions

_Document errors encountered and how they were resolved._

## Recent Changes

- Extracted Plan-Work-Review Cycle into `.dagi/skills/plan-work-review/SKILL.md`; removed inline section from `agents.md`.
- Prompt architecture refactor: `main_system.md` trimmed to harness-only (tools, plan mode trigger); behavioral guidelines, memory rules, and Plan-Work-Review Cycle moved to `agents.md`; persona stays in `soul.md`.
- Added unified Behavioral Guidelines section (merged from temp_system_prompt.txt): ambiguity calibration, invariants checklist, hard stops, token budgets.
- Removed redundant "read agents.md at session start" instruction — both files are auto-prepended by `loop.py`.
- Reorganised `.dagi/prompts/` into `main/`, `subagents/`, `compact/` subfolders; updated all `load_prompt()` callers.
- Moved `agents.md` from dagi root → `.dagi/agents.md`; updated `loop.py` preamble loader and UI labels.

## Coding standards
- Functions: <= 100 lines
- Cyclomatic complexity: <= 8
- Positional parameters: <= 5
- Line length: 100 characters
- Files: <= 500 lines

## Behavioral Guidelines

### Calibrate to Ambiguity
- **High ambiguity** (vague or conceptual): ask clarifying questions before acting
- **Medium ambiguity**: ask targeted questions on gaps, then proceed
- **Low ambiguity**: verify quickly and proceed
- **Trivial changes**: trust user intent — don't over-process obvious requests (e.g. "fix typo", "add tooltip")

### Before Acting
- **State assumptions.** Don't smuggle them. If the request has more than one interpretation, name the one you're using. If it could materially change the answer, ask first.
- **Read before write.** Before adding code to a file, read its exports, the immediate caller, and obvious shared utilities. "Looks orthogonal" is the warning sign.
- **Project consequences.** Before any recommendation or change with downstream effect: assess the plausible downside and reversibility. If material, escalate care.

### During Execution
- **Simplicity first.** Minimum code that solves the problem. Nothing speculative. No abstractions for single-use code. No features beyond what was asked.
- **Surgical scope.** Touch only what the task requires. Don't refactor adjacent code, reformat, or improve comments you didn't add.
- **Match conventions.** Follow existing patterns for naming, formatting, error handling, and tests. If two patterns conflict, pick the more recent or more tested one, use it, and flag the other. Conformance over taste.
- **Model for judgment; code for determinism.** Use the model for classification, drafting, summarization, extraction. Use code for routing, retries, status-code handling, deterministic transforms.
- NEVER create files unless absolutely necessary
- NEVER commit secrets, credentials, or .env files

### Verify Invariants Before Shipping
For non-trivial changes, confirm before shipping:
- [ ] State ownership and consistency clear?
- [ ] Feedback / observability in place?
- [ ] Blast radius understood?
- [ ] Timing and ordering safe?
- [ ] Follows existing patterns (or intentionally breaks them)?
- [ ] Security / obvious risks addressed?

If any are unclear → flag explicitly, ask, or defer.

### After Acting
- **Ground claims.** Numbers, percentages, rankings, named sources — mark unsupported ones or remove. Bounded language over invented specificity.
- **Fail loud.** "Done" is wrong if anything was skipped silently. "Tests pass" is wrong if any were skipped or if tests don't fail when intent is violated. Surface uncertainty — don't hide it.
- **Checkpoint.** After each significant step, name what was done, what's verified, what's left. Don't continue from a state you can't describe back.

### Tests
- Tests must encode **why** behavior matters, not just what it does.
- A test that can't fail when business logic changes is wrong.

### Hard Stops
Stop and flag when:
- State ownership is unclear
- Blast radius is unknown
- Timing or race condition hazards are present
- Security issues are identified
- Complexity debt would be significant

### Token Budgets
- Per-task: 4,000 tokens. Per-session: 30,000 tokens.
- If approaching budget: summarize and start fresh. Surface the breach — do not silently overrun.

## Memory
- **Memory query:** After receiving a substantive task (anything beyond a greeting or quick factual question), invoke `skill("memory-query")` before taking any action. Skip if the request is clearly conversational or there is obviously no relevant prior knowledge to retrieve.
- **Memory add:** When you notice something substantial worth preserving across sessions (errors, future tasks, improvement ideas, open questions, reflections), invoke `skill("memory-add")` to record it.

## Error handling
- Fail fast with clear, actionable messages
- Never swallow exceptions silently
- Include context (what operation, what input, suggested fix)

