from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import openai

from agent.registry import ToolRegistry
from agent.session import SessionTracker, ToolCallRecord
from agent.skills import Skill, SkillLoader
from tools.compact import CompactTool, CompactionResult
from tools.plan_mode import ENTER_PLAN_MODE_SENTINEL, EXIT_PLAN_MODE_SENTINEL


def _format_tools_and_skills(registry: ToolRegistry, skills: list[Skill]) -> str:
    """Generate a unified tools + skills section for the system prompt."""
    lines = ["## Available Tools", ""]
    for name, description in registry.list_tools():
        lines.append(f"- **{name}**: {description}")

    if skills:
        lines += [
            "",
            "## Available Skills",
            "",
            "Skills are detailed guidance documents for specific workflows. "
            "Invoke the `skill` tool autonomously whenever a task matches a skill's "
            "purpose — do not wait for the user to ask.",
            "",
        ]
        for s in sorted(skills, key=lambda x: x.name):
            desc = f" — {s.description}" if s.description else ""
            lines.append(f"- **{s.name}**{desc}")

    return "\n".join(lines)


DEFAULT_SYSTEM_PROMPT = """\
You are an expert coding assistant. You help users with coding tasks by reading files, executing commands, editing code, and writing new files.

{tools_and_skills}

Use `tool_search` to discover additional capabilities (web research, file exploration) not listed above.

Guidelines:
- Use grep and find instead of bash for searching/discovering files
- Use read to examine files before editing
- Use edit for precise changes (old text must match exactly)
- Use write only for new files or complete rewrites
- All file paths are relative to the project root unless absolute
- When searching for files, always search in the project root first. Only access `dagi-memory/` or `.dagi/` when explicitly performing memory/wiki operations (memory-add, memory-ingest, memory-query, memory-lint skills)
- When summarizing your actions, output plain text directly - do NOT use cat or bash to display what you did
- Be concise in your responses
- Show file paths clearly when working with files
- Never stop mid-task. Keep calling tools until the task is fully complete before returning a plain-text response.
- If you have completed one step but further steps remain, call the next required tool immediately — do not summarize partial progress as a final answer.
- A response with no tool calls signals task completion. Only emit one when every required action has been taken and the result is ready to present.
- Memory: When you notice something substantial worth preserving across sessions (future tasks, improvement ideas, open questions, reflections), invoke skill("memory-add"). Use sparingly — significant insights only.

Documentation:
- Your own documentation (including custom model setup and theme creation) is at: {readme_path}
- Read it when users ask about features, configuration, or setup, and especially if the user asks you to add a custom model or provider, or create a custom theme.

## Autonomous Plan Mode

Call `enter_plan_mode` when the task has ANY of these characteristics:
- Requires 3 or more distinct implementation steps across different files
- Involves architectural decisions with non-trivial trade-offs (new abstractions, interface changes, new dependencies)
- Touches multiple subsystems or requires broad exploration before acting
- Has requirements ambiguous enough that a wrong choice would require significant rework

Do NOT enter plan mode for:
- Single-file edits or clearly scoped additions
- Bug fixes where the root cause and fix are already clear
- Tasks already fully specified with no design decisions remaining

During dagi-initiated plan mode: explore autonomously with read/grep/find, write the plan document, then call `exit_plan_mode` immediately to restore full tools and begin implementation.\
"""


_PLAN_MODE_SYSTEM_ADDENDUM = """

---

## PLAN MODE ACTIVE

You are in read-only planning mode. Your capabilities are restricted:
- **READ**: You can read any file in the project.
- **WRITE**: You may ONLY write to this plan document: `{plan_file}`
- **BLOCKED**: bash, shell commands, and writes to any other file are unavailable.

Your objective is to produce a comprehensive plan document.
Explore the codebase as needed with read/grep/find. Write the plan to `{plan_file}`.

The plan document must include:
1. **Context** — what problem is being solved and why
2. **Approach** — the chosen strategy and key architectural decisions
3. **Files to modify** — exact file paths and line references
4. **Step-by-step implementation** — ordered, concrete steps
5. **Todo list** — checkboxes (`- [ ]`) for each discrete action
6. **Verification** — how to test that the implementation is correct

{ask_user_instruction}

When the plan is complete, call `exit_plan_mode` to restore full tools and begin implementation."""


_PLAN_MODE_ASK_USER_INSTRUCTION = (
    "Use `ask_user` to present solution options and resolve key decisions before finalising the plan. "
    "Provide 2-4 concrete options; mark the strongest with recommended=true."
)
_PLAN_MODE_NO_ASK_INSTRUCTION = (
    "Plan autonomously — explore, decide, and write the plan without waiting for user input. "
    "Call `exit_plan_mode` as soon as the plan is complete."
)


@dataclass
class AgentConfig:
    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""  # always set by agent.config_loader.resolve_model_config
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    thread_id: str | None = None
    thinking: str = "none"  # "none" | "low" | "medium" | "high"
    # Compaction (Pi-style)
    context_window: int = 128_000     # model's hard token limit
    reserve_tokens: int = 16_384      # headroom for summary response + next reply
    keep_recent_tokens: int = 20_000  # tail kept verbatim (token budget)
    # Project scope
    project_path: Path = field(default_factory=lambda: Path(".").resolve())
    # Plan mode
    plan_mode: bool = False
    plan_file: str | None = None  # absolute path to the active plan document
    plan_mode_initiated_by: str = "user"  # "user" | "dagi"
    # Worker model (cheaper LLM for sub-agents); None = use this config as-is
    worker_config: AgentConfig | None = field(default=None)


@dataclass
class AgentCallbacks:
    """Optional observer hooks for the agent loop. All default to no-ops so the
    CLI path pays zero cost. The UI wires these to queue events for live updates."""
    on_tool_start:     Callable[[str, str, str], None]          = field(default=lambda n, d, a: None)
    on_tool_end:       Callable[[str, str], None]               = field(default=lambda n, r: None)
    on_assistant_text: Callable[[str], None]                    = field(default=lambda t: None)
    on_token_update:   Callable[[int, int, float | None, int], None] = field(default=lambda i, o, c, t: None)
    on_iteration:      Callable[[int], None]                    = field(default=lambda cur: None)
    on_done:           Callable[[str], None]                    = field(default=lambda r: None)
    on_error:          Callable[[Exception], None]              = field(default=lambda e: None)
    on_api_call:       Callable[[list], None]                   = field(default=lambda msgs: None)
    on_reasoning:      Callable[[str], None]                    = field(default=lambda text: None)
    on_compaction:     Callable[[int, int], None]               = field(default=lambda kept, removed: None)
    on_ask_user:       Callable[[str, list], str]               = field(
        default=lambda question, options: next(
            (o["label"] for o in options if o.get("recommended")),
            options[0]["label"] if options else "",
        )
    )


def _extract_reasoning(message) -> str:
    """Get reasoning text from the response message, trying SDK attr then model_extra."""
    text = getattr(message, "reasoning_content", None) or ""
    if not text:
        extras = getattr(message, "model_extra", None) or {}
        text = extras.get("reasoning", "")
    return text or ""


class _SafeDict(dict):
    """Format-map helper: leaves unknown {key} placeholders intact."""
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


class AgentLoop:
    def __init__(
        self,
        config: AgentConfig,
        callbacks: AgentCallbacks | None = None,
        initial_messages: list | None = None,
        _registry: "ToolRegistry | None" = None,
        _parent_tracker: "SessionTracker | None" = None,
        _subagent_id: str | None = None,
        _tracker: "SessionTracker | None" = None,
    ):
        from agent.tools import create_tool_registry
        from uuid import uuid4

        self.callbacks = callbacks or AgentCallbacks()
        dagi_root = Path(__file__).parent.parent

        # ── Create tracker first so sub-agent tools can reference it ─────────
        if _tracker is not None:
            self.tracker = _tracker
        elif _parent_tracker is not None:
            self.tracker = _parent_tracker.child_tracker(_subagent_id or uuid4().hex)
        else:
            self.tracker = SessionTracker(model=config.model, thread_id=config.thread_id)

        if _registry is not None:
            # Sub-agent path: use the provided registry, skip skill loading
            self.registry = _registry
            self.skills = []
        else:
            # ── Load skills ───────────────────────────────────────────────────
            skill_roots = [
                dagi_root / ".dagi" / "skills",
                config.project_path / ".dagi" / "skills",
            ]
            self.skills = SkillLoader().load_all(skill_roots, dagi_root=dagi_root)

            # ── Build registry bound to project path ──────────────────────────
            self.registry = create_tool_registry(
                cwd=config.project_path,
                allowed_roots=[dagi_root, config.project_path],
                skill_roots=skill_roots,
                plan_mode=config.plan_mode,
                plan_file=Path(config.plan_file) if config.plan_file else None,
                plan_mode_initiated_by=config.plan_mode_initiated_by,
                config=config,
                callbacks=self.callbacks,
                tracker=self.tracker,
            )

        # ── Build system prompt ───────────────────────────────────────────
        readme_path = (dagi_root / "README.md").resolve()
        tools_and_skills_section = _format_tools_and_skills(self.registry, self.skills)
        prompt = config.system_prompt.format_map(_SafeDict(
            readme_path=readme_path,
            tools_and_skills=tools_and_skills_section,
        ))

        # Load preamble: dagi root soul/agents, then project .dagi/AGENTS.md
        preamble_parts: list[str] = []
        for filename in ("soul.md", "agents.md"):
            p = dagi_root / filename
            if p.exists():
                preamble_parts.append(p.read_text(encoding="utf-8").strip())
        project_agents = config.project_path / ".dagi" / "AGENTS.md"
        if project_agents.exists():
            text = project_agents.read_text(encoding="utf-8").strip()
            if text:
                preamble_parts.append(text)
        preamble = "\n\n---\n\n".join(preamble_parts)

        sections = [s for s in [preamble, prompt] if s]
        system = "\n\n---\n\n".join(sections)

        # Project context line appended to system prompt
        system += f"\n\n---\n\nProject root: {config.project_path}"

        if config.plan_mode and config.plan_file:
            ask_instr = (
                _PLAN_MODE_ASK_USER_INSTRUCTION
                if config.plan_mode_initiated_by == "user"
                else _PLAN_MODE_NO_ASK_INSTRUCTION
            )
            system += _PLAN_MODE_SYSTEM_ADDENDUM.format(
                plan_file=config.plan_file,
                ask_user_instruction=ask_instr,
            )

        # Build labeled system-prompt sections for the UI expander
        self.system_parts: list[dict] = []
        for filename, label in [("soul.md", "SOUL.md"), ("agents.md", "AGENTS.md")]:
            p = dagi_root / filename
            if p.exists():
                self.system_parts.append({"label": label, "content": p.read_text(encoding="utf-8").strip()})
        self.system_parts.append({"label": "System Prompt", "content": prompt})

        if initial_messages:
            # multi-turn: continue from existing conversation history
            self._messages = list(initial_messages)
        else:
            self._messages = [{"role": "system", "content": system}]

        self.client = openai.OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.config = config
        # Build the extra_body for reasoning/thinking (OpenRouter extension)
        self._reasoning_extra: dict = {}
        if config.thinking and config.thinking.lower() != "none":
            self._reasoning_extra = {"reasoning": {"effort": config.thinking.lower()}}
        self.tracker.record_system(system)

        # ── Compaction tool (internal-only, not in ToolRegistry) ──────────
        self.compact_tool = CompactTool()
        self.compact_tool.bind(
            self._messages, config, self.client,
            on_compaction=self.callbacks.on_compaction,
        )

    def _compact_context(self) -> CompactionResult:
        """Delegates to CompactTool.compact()."""
        return self.compact_tool.compact()

    def run(self, task: str) -> str:
        self._messages.append({"role": "user", "content": task})
        self.tracker.record_user(task)

        try:
            iteration = 0
            while True:
                iteration += 1
                self.callbacks.on_iteration(iteration)

                self.callbacks.on_api_call(list(self._messages))
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=self._messages,
                    tools=self.registry.get_openai_tools_list(),
                    parallel_tool_calls=False,
                    **(dict(extra_body=self._reasoning_extra) if self._reasoning_extra else {}),
                )
                message = response.choices[0].message
                _reasoning = _extract_reasoning(message)
                if _reasoning:
                    self.callbacks.on_reasoning(_reasoning)

                tool_records: list[ToolCallRecord] = []

                if not message.tool_calls:
                    # store assistant turn as dict to keep _messages serialisable
                    self._messages.append({"role": "assistant", "content": message.content})
                    result = message.content or ""
                    self.callbacks.on_assistant_text(result)
                    _thinking_tok = (
                        getattr(getattr(response.usage, "completion_tokens_details", None), "reasoning_tokens", None)
                        or 0
                    )
                    self.callbacks.on_token_update(
                        getattr(response.usage, "prompt_tokens", 0) or 0,
                        getattr(response.usage, "completion_tokens", 0) or 0,
                        getattr(response.usage, "cost", None),
                        _thinking_tok,
                    )
                    self.tracker.record_assistant(message.content, response.usage, tool_records)
                    self.callbacks.on_done(result)
                    return result

                # Interleave: each tool call is immediately followed by its result.
                # First call carries the assistant's text content; subsequent ones get None.
                if message.content:
                    self.callbacks.on_assistant_text(message.content)

                first = True
                for tc in message.tool_calls:
                    self._messages.append({
                        "role": "assistant",
                        "content": message.content if first else None,
                        "tool_calls": [{
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }],
                    })
                    first = False

                    tool_obj = self.registry._tools.get(tc.function.name)
                    description = tool_obj.description if tool_obj else tc.function.name
                    self.callbacks.on_tool_start(tc.function.name, description, tc.function.arguments)
                    self.tracker.record_tool_start(tc.function.name, description, tc.function.arguments)

                    result = self.registry.dispatch(
                        tc.function.name, json.loads(tc.function.arguments)
                    )
                    if result == ENTER_PLAN_MODE_SENTINEL:
                        result = self._handle_enter_plan_mode(json.loads(tc.function.arguments))
                    elif result == EXIT_PLAN_MODE_SENTINEL:
                        result = self._handle_exit_plan_mode(json.loads(tc.function.arguments))
                    result_str = result if isinstance(result, str) else "__list__:" + json.dumps(result)
                    self.callbacks.on_tool_end(tc.function.name, result_str)
                    self.tracker.record_tool_end(tc.function.name, result_str)

                    tool_records.append(ToolCallRecord(
                        name=tc.function.name,
                        description=description,
                        input=tc.function.arguments,
                        result=result_str,
                    ))
                    self._messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result}
                    )

                self.tracker.record_assistant(message.content, response.usage, tool_records)
                _thinking_tok = (
                    getattr(getattr(response.usage, "completion_tokens_details", None), "reasoning_tokens", None)
                    or 0
                )
                self.callbacks.on_token_update(
                    getattr(response.usage, "prompt_tokens", 0) or 0,
                    getattr(response.usage, "completion_tokens", 0) or 0,
                    getattr(response.usage, "cost", None),
                    _thinking_tok,
                )

                # ── Compaction trigger ────────────────────────────────────────
                _prompt_tok = getattr(response.usage, "prompt_tokens", 0) or 0
                if (
                    self.config.context_window > 0
                    and _prompt_tok > 0
                    and _prompt_tok > self.config.context_window - self.config.reserve_tokens
                ):
                    self._compact_context()
                # ─────────────────────────────────────────────────────────────

        except Exception as e:
            self.callbacks.on_error(e)
            raise

    # ── Plan mode transitions ─────────────────────────────────────────────────

    def _handle_enter_plan_mode(self, args: dict) -> str:
        reason = args.get("reason", "")
        dagi_root = Path(__file__).parent.parent
        plans_dir = self.config.project_path / ".dagi" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_file = plans_dir / f"plan_{ts}.md"
        plan_file.write_text(
            f"# Plan — {ts}\n\n"
            "## Context\n\n\n"
            "## Approach\n\n\n"
            "## Files to Modify\n\n\n"
            "## Implementation Steps\n\n\n"
            "## Todo List\n\n"
            "- [ ] \n\n"
            "## Verification\n\n",
            encoding="utf-8",
        )
        self._rebuild_for_plan_mode(dagi_root, plan_file)
        return (
            f"Plan mode activated (initiated by dagi). Plan document: {plan_file}\n"
            f"Reason: {reason}\n"
            "Tools restricted: read/grep/find + plan file write only (bash unavailable). "
            "Explore, write the plan, then call exit_plan_mode."
        )

    def _handle_exit_plan_mode(self, args: dict) -> str:
        summary = args.get("summary", "")
        saved_plan = self.config.plan_file
        dagi_root = Path(__file__).parent.parent
        self._rebuild_for_normal_mode(dagi_root)
        return (
            f"Plan mode exited. Full tool access restored.\n"
            f"Plan summary: {summary}\n"
            f"Plan document: {saved_plan}\n"
            "Proceed to implement according to the plan immediately."
        )

    def _rebuild_for_plan_mode(self, dagi_root: Path, plan_file: Path) -> None:
        from agent.tools import create_tool_registry

        self.config.plan_mode = True
        self.config.plan_file = str(plan_file)
        self.config.plan_mode_initiated_by = "dagi"

        skill_roots = [
            dagi_root / ".dagi" / "skills",
            self.config.project_path / ".dagi" / "skills",
        ]
        self.registry = create_tool_registry(
            cwd=self.config.project_path,
            allowed_roots=[dagi_root, self.config.project_path],
            skill_roots=skill_roots,
            plan_mode=True,
            plan_file=plan_file,
            plan_mode_initiated_by="dagi",
            config=self.config,
            callbacks=self.callbacks,
            tracker=self.tracker,
        )

        tools_and_skills = _format_tools_and_skills(self.registry, self.skills)
        readme_path = (dagi_root / "README.md").resolve()
        new_system = self.config.system_prompt.format_map(_SafeDict(
            readme_path=readme_path,
            tools_and_skills=tools_and_skills,
        ))
        new_system += f"\n\n---\n\nProject root: {self.config.project_path}"
        new_system += _PLAN_MODE_SYSTEM_ADDENDUM.format(
            plan_file=plan_file,
            ask_user_instruction=_PLAN_MODE_NO_ASK_INSTRUCTION,
        )
        self._messages[0] = {"role": "system", "content": new_system}
        self.compact_tool.bind(
            self._messages, self.config, self.client,
            on_compaction=self.callbacks.on_compaction,
        )

    def _rebuild_for_normal_mode(self, dagi_root: Path) -> None:
        from agent.tools import create_tool_registry

        self.config.plan_mode = False
        self.config.plan_file = None
        self.config.plan_mode_initiated_by = "user"

        skill_roots = [
            dagi_root / ".dagi" / "skills",
            self.config.project_path / ".dagi" / "skills",
        ]
        self.registry = create_tool_registry(
            cwd=self.config.project_path,
            allowed_roots=[dagi_root, self.config.project_path],
            skill_roots=skill_roots,
            plan_mode=False,
            plan_file=None,
            plan_mode_initiated_by="user",
            config=self.config,
            callbacks=self.callbacks,
            tracker=self.tracker,
        )

        tools_and_skills = _format_tools_and_skills(self.registry, self.skills)
        readme_path = (dagi_root / "README.md").resolve()
        new_system = self.config.system_prompt.format_map(_SafeDict(
            readme_path=readme_path,
            tools_and_skills=tools_and_skills,
        ))
        new_system += f"\n\n---\n\nProject root: {self.config.project_path}"
        self._messages[0] = {"role": "system", "content": new_system}
        self.compact_tool.bind(
            self._messages, self.config, self.client,
            on_compaction=self.callbacks.on_compaction,
        )

    def finish(self) -> None:
        """Finalize the session — write session_end to JSONL. Called by the CLI at session end."""
        self.tracker.finish(raw_messages=self._messages)
