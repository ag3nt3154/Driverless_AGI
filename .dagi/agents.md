# Project: Driverless_AGI (dagi)

> **Last updated:** 2026-05-03

## Description

dagi is a self-contained agentic coding assistant engine. It runs an OpenAI-compatible agentic loop that can read, write, edit, and execute code across a local project. It is also capable of self-improvement — extending its own tools, skills, and prompts.

## Objectives

- Provide a reliable, extensible agentic coding loop compatible with any OpenAI-compatible LLM endpoint.
- Support project-local customisation via `.dagi/` scaffolding (tools, skills, workflows, agents.md).
- Enable self-improvement through the `review-session` skill and `improve-yourself` workflow.

## Directory Structure

```
Driverless_AGI/
├── agent/              # Core engine — loop, registry, tools, prompts, session tracking
├── tools/              # Built-in tools (compact, plan_subagent, explore_files, web_research, etc.)
├── scripts/            # Utility scripts (dagi_freeze, build_api_tools, etc.)
├── projects/           # Experimental sub-projects (prompt_opt, etc.)
├── .dagi/
│   ├── agents.md       # This file — dagi engine context loaded every session
│   ├── prompts/
│   │   ├── main/       # main_system.md — primary agent system prompt
│   │   ├── subagents/  # plan_subagent, explore_files, web_research prompts
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

- Reorganised `.dagi/prompts/` into `main/`, `subagents/`, `compact/` subfolders; updated all `load_prompt()` callers.
- Added `{dagi_root}` template variable to system prompt and `format_map` injection.
- Fixed `_rebuild_for_normal_mode` missing `cwd`, `memory_root`, `dagi_root` in its `format_map`.
- Moved `agents.md` from dagi root → `.dagi/agents.md`; updated `loop.py` preamble loader and UI labels.
- Updated `/init` to scaffold `.dagi/agents.md` with section headers instead of empty file.
