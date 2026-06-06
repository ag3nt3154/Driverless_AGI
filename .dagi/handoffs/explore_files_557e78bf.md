# Exploration Report: Driverless_AGI Codebase Structure

## Summary

Driverless_AGI (dagi) is a self-contained agentic coding assistant engine.
The architecture is centred on agent/loop.py (the AgentLoop class).
It orchestrates a tool-calling REPL with context compaction, multi-tier models, pipe-mode subagents, skills, workflows, BM25 memory, and JSONL logging.


## Key Files

| File | Purpose |
|------|---------|
| cli.py | Interactive REPL CLI (typer + Rich) |
| tui.py | Textual TUI entry point |
| main.py | Single-shot argparse CLI |
| agent/loop.py | Core engine: AgentLoop, AgentConfig, AgentCallbacks |
| agent/config_loader.py | YAML config resolver |
| agent/tools.py | create_tool_registry() |
| agent/registry.py | ToolRegistry name-BaseTool mapping |
| agent/base_tool.py | BaseTool ABC |
| agent/skills.py | SkillLoader for SKILL.md files |
| agent/workflows.py | WorkflowLoader for workflow.md files |
| agent/session.py | SessionTracker JSONL logging |
| agent/sub_agent.py | SubAgentRunner in-process subagent |
| agent/prompts.py | Prompt file loader |
| agent/memory_retriever.py | BM25 wiki retrieval |
| .dagi/agents.md | Project context + guidelines |
| soul.md | Agent persona (Dagi-chan) |
| config.yaml | Runtime config |
| scripts/dagi_freeze.py | Snapshot/restore utility |
| tools/_subagent_runner.py | Pipe-mode subagent runner |


## Findings

### 1. Top-Level Directory Structure

Root directories: agent/ (11 modules), tools/ (28 files), scripts/ (2), projects/ (4), tests/ (5), archive/, snapshots/, .dagi/
Root files: cli.py, tui.py, main.py, hist.py, config.yaml, config.example.yaml, README.md, SOUL.md, TODO.md, pyproject.toml

### 2. agent/ -- Core Engine (11 modules)

Modules: __init__.py, base_tool.py (ABC), registry.py (ToolRegistry), tools.py (builder), loop.py (engine), config_loader.py (config), prompts.py (loader), skills.py (loader), workflows.py (loader), session.py (logging), sub_agent.py (runner), memory_retriever.py (BM25)

### 3. Core Engine Loop Architecture

AgentLoop.run(task): 1) Append task, 2) Infinite loop: call OpenAI API, handle ghost retries, 3) No tool calls: check END_OF_RESPONSE flag or inject continue.md, 4) Tool calls: dispatch via ToolRegistry, 5) Handle plan mode sentinels + model switching, 6) Compaction when near token limit
System prompt: soul.md + dagi agents.md + project agents.md + main_system.md

### 4. tools/ -- Built-in Tools (28 files)

File I/O: ReadTool, WriteTool, EditTool, CopyTool, GrepTool, FindTool. Execution: BashTool. Git: GitStatusTool, GitCommitTool, GitRollbackTool.
Control: EnterPlanModeTool, ExitPlanModeTool, SwitchModelTool, ReloadSkillsTool, CompactTool, ExtendSubagentTimeoutTool, AskUserTool, EmoteTool.
Web: WebSearchTool, WebFetchTool, WebResearchTool. Subagents: ExploreFilesTool, SpawnSubagentTool, SpawnCliSubagentTool, PlanSubAgent.
Skills: SkillTool, RunSkillScriptTool, ShowPlanTool. Internal: _path_guard.py, _plan_parser.py, _subagent_runner.py

### 5. .dagi/ Directory Structure

agents.md, prompts/ (main, compact), subagents/ (6 types: explore_files, web_research, worker, review, plan, cli)
skills/ (13): build-api-tools, create-skill, gnhf, grill-me, memory-add, memory-discuss, memory-ingest, memory-lint, memory-query, plan-work-review, review-session, talk-to-user, write-novel
workflow/ (1): improve-yourself. tools/ (3): confidence_decay.py, datetime_now.py, parse_session_log.py
plans/, logs/ (100+ sessions), self-review/, handoffs/, memory/wiki/, subagent_logs/, emotes/ (5), gnhf/, benchmark/

### 6. Entry Points

cli.py: REPL (typer+Rich) with threaded/sync modes, slash commands, skill/workflow dispatch
tui.py: Textual TUI with header panels and scrollable conversation
main.py: Legacy argparse CLI

### 7. Configuration

config.yaml: default_model, worker_model, advanced_model, memory_root, thinking, context_window, reserve, keep_recent, max_iterations, max_continuations, null_response_retries, cli section, models catalog
agent/config_loader.py resolves config. CLI -> config_loader -> AgentLoop.

### 8. Architectural Patterns

- Tools: BaseTool subclasses -> create_tool_registry() for normal vs plan mode
- Subagents: pipe (modern) vs in-process (legacy)
- Skills: autodiscoverable; Workflows: user-only slash commands
- Session tracking: JSONL with child tracker rollup
- Compaction: Pi-style summarisation
- Model tiers: default, worker, advanced

## Recommendations

1. Start with agent/loop.py
2. agent/tools.py is tool wiring hub
3. .dagi/ is extension mechanism
4. AgentCallbacks is UI boundary
5. Two subagent patterns: pipe vs in-process
6. config_loader.py is config SSoT
7. Tests in tests/ (5 files)
