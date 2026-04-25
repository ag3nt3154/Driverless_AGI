from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import openai

from agent.prompts import load_prompt
from agent.registry import ToolRegistry
from agent.session import SessionTracker, ToolCallRecord
from agent.skills import Skill, SkillLoader
from tools.compact import CompactTool, CompactionResult
from tools.plan_mode import ENTER_PLAN_MODE_SENTINEL, EXIT_PLAN_MODE_SENTINEL


def _is_plan_empty(path: Path) -> bool:
    """Return True if the plan file has no meaningful content beyond scaffold boilerplate."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return True
    meaningful = [
        line for line in text.splitlines()
        if line.strip()
        and not line.strip().startswith("#")
        and line.strip() not in ("- [ ]", "- [ ] ", "- [x]")
    ]
    return len(meaningful) == 0


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
            "You MUST invoke the relevant `skill` tool BEFORE beginning any task for which "
            "a matching skill exists. Treat skill invocation as a required first step — "
            "never implement a skill-governed workflow without loading it first. "
            "If the user's request matches a skill's description or any of its trigger phrases, "
            "call `skill(name)` immediately as your first action. "
            "Skills may include executable scripts — after loading a skill, use "
            "`run_skill_script(skill_name, script_name)` to run them.",
            "",
        ]
        for s in sorted(skills, key=lambda x: x.name):
            desc = f" — {s.description}" if s.description else ""
            lines.append(f"- **{s.name}**{desc}")
            if s.triggers:
                quoted = ", ".join(f'"{t}"' for t in s.triggers)
                lines.append(f"  Triggers: {quoted}")

    return "\n".join(lines)


DEFAULT_SYSTEM_PROMPT = load_prompt("main_system.md")


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
    # Plan model (dedicated LLM for the plan subagent); None = use this config as-is
    plan_config: AgentConfig | None = field(default=None)
    # Active plan file persisted in system prompt after plan mode exits
    active_plan_file: str | None = None


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

        # Set when DAGI calls exit_plan_mode; signals run() to stop iterating
        self.plan_mode_exited: bool = False
        self.exited_plan_file: str | None = None

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

                if self.plan_mode_exited:
                    self.callbacks.on_done("")
                    return ""

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
        from tools.plan_subagent import PlanSubAgent

        # Snapshot whether plan mode was user-initiated (harness pre-set plan_mode=True)
        # before we rebuild back to normal mode below.
        was_user_initiated = self.config.plan_mode

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

        self.callbacks.on_assistant_text(
            f"Entering plan mode — spawning plan subagent.\n\n"
            f"**Plan file:** `{plan_file}`\n\n**Reason:** {reason}"
        )

        subagent = PlanSubAgent(
            config=self.config,
            plan_file=plan_file,
            callbacks=self.callbacks,
            tracker=self.tracker,
        )
        task = (
            f"Write a comprehensive implementation plan for the following task:\n\n"
            f"{reason}\n\n"
            f"Project root: {self.config.project_path}\n"
            f"Plan file path: {plan_file}\n\n"
            f"Explore the codebase thoroughly, then overwrite the scaffold at {plan_file} "
            f"with your complete plan document."
        )
        subagent.run(task)

        try:
            plan_contents = plan_file.read_text(encoding="utf-8")
        except Exception:
            plan_contents = "(plan file could not be read)"

        self.config.active_plan_file = str(plan_file)
        self.exited_plan_file = str(plan_file)
        self._rebuild_for_normal_mode(dagi_root)

        if was_user_initiated:
            # show_plan tool already displayed the plan and ran the modification loop.
            self.plan_mode_exited = True
            return f"Plan written to {plan_file}. Awaiting user review."
        else:
            # DAGI-initiated: return plan contents as tool result so the agent
            # continues executing in the same turn.
            if _is_plan_empty(plan_file):
                return (
                    f"The plan document at {plan_file} is empty. "
                    "Stop immediately and ask the user for further directions "
                    "before doing anything else."
                )
            return (
                f"Plan written to {plan_file}. Returning to normal mode to execute.\n\n"
                f"{plan_contents}"
            )

    def _handle_exit_plan_mode(self, args: dict) -> str:
        summary = args.get("summary", "")
        saved_plan = self.config.plan_file
        self.plan_mode_exited = True
        self.exited_plan_file = saved_plan
        dagi_root = Path(__file__).parent.parent
        self._rebuild_for_normal_mode(dagi_root)
        if saved_plan and _is_plan_empty(Path(saved_plan)):
            return (
                "The plan document is empty. "
                "Stop immediately and ask the user for further directions "
                "before doing anything else."
            )
        return (
            f"Plan complete. Awaiting user review before implementation begins.\n"
            f"Plan summary: {summary}\n"
            f"Plan document: {saved_plan}"
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

        if self.config.active_plan_file:
            new_system += (
                f"\n\n---\n\n"
                f"## Active Plan\n\n"
                f"A plan document is active at: `{self.config.active_plan_file}`\n\n"
                f"As you implement each step:\n"
                f"- Read the plan file when the user asks about progress.\n"
                f"- After completing each todo item, edit the plan file and tick its "
                f"checkbox: `- [ ]` → `- [x]`.\n"
                f"- If you deviate from the plan, update the plan document to reflect reality."
            )

        self._messages[0] = {"role": "system", "content": new_system}
        self.compact_tool.bind(
            self._messages, self.config, self.client,
            on_compaction=self.callbacks.on_compaction,
        )

    def finish(self) -> None:
        """Finalize the session — write session_end to JSONL. Called by the CLI at session end."""
        self.tracker.finish(raw_messages=self._messages)
