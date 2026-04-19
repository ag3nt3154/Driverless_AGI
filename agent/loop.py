import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import openai

from agent.registry import ToolRegistry
from agent.session import SessionTracker, ToolCallRecord
from agent.skills import Skill, SkillLoader
from tools.compact import CompactTool, CompactionResult


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

Guidelines:
- Use grep and find instead of bash for searching/discovering files
- Use read to examine files before editing
- Use edit for precise changes (old text must match exactly)
- Use write only for new files or complete rewrites
- All file paths are relative to the project root unless absolute
- When summarizing your actions, output plain text directly - do NOT use cat or bash to display what you did
- Be concise in your responses
- Show file paths clearly when working with files

Documentation:
- Your own documentation (including custom model setup and theme creation) is at: {readme_path}
- Read it when users ask about features, configuration, or setup, and especially if the user asks you to add a custom model or provider, or create a custom theme.\
"""


@dataclass
class AgentConfig:
    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""  # always set by agent.config_loader.resolve_model_config
    max_iterations: int = 20
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


@dataclass
class AgentCallbacks:
    """Optional observer hooks for the agent loop. All default to no-ops so the
    CLI path pays zero cost. The UI wires these to queue events for live updates."""
    on_tool_start:     Callable[[str, str, str], None]          = field(default=lambda n, d, a: None)
    on_tool_end:       Callable[[str, str], None]               = field(default=lambda n, r: None)
    on_assistant_text: Callable[[str], None]                    = field(default=lambda t: None)
    on_token_update:   Callable[[int, int, float | None, int], None] = field(default=lambda i, o, c, t: None)
    on_iteration:      Callable[[int, int], None]               = field(default=lambda cur, mx: None)
    on_done:           Callable[[str], None]                    = field(default=lambda r: None)
    on_error:          Callable[[Exception], None]              = field(default=lambda e: None)
    on_api_call:       Callable[[list], None]                   = field(default=lambda msgs: None)
    on_reasoning:      Callable[[str], None]                    = field(default=lambda text: None)
    on_compaction:     Callable[[int, int], None]               = field(default=lambda kept, removed: None)


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
    ):
        from agent.tools import create_tool_registry

        self.callbacks = callbacks or AgentCallbacks()
        dagi_root = Path(__file__).parent.parent

        if _registry is not None:
            # Sub-agent path: use the provided registry, skip skill loading
            self.registry = _registry
            self.skills = []
        else:
            # ── Load skills ───────────────────────────────────────────────────
            skill_roots = [
                config.project_path / ".dagi" / "skills",
                dagi_root / ".dagi" / "skills",
            ]
            self.skills = SkillLoader().load_all(skill_roots)

            # ── Build registry bound to project path ──────────────────────────
            self.registry = create_tool_registry(
                cwd=config.project_path,
                allowed_roots=[dagi_root, config.project_path],
                skills=self.skills or None,
                plan_mode=config.plan_mode,
                plan_file=Path(config.plan_file) if config.plan_file else None,
                config=config,
                callbacks=self.callbacks,
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
            system += f"""

---

## PLAN MODE ACTIVE

You are in read-only planning mode. Your capabilities are restricted:
- **READ**: You can read any file in the project.
- **WRITE**: You may ONLY write to this plan document: `{config.plan_file}`
- **BLOCKED**: bash, shell commands, and writes to any other file are unavailable.

Your objective is to collaborate interactively with the user to produce a comprehensive plan.
Ask clarifying questions. Explore the codebase as needed. Then write your plan to `{config.plan_file}`.

The plan document must include:
1. **Context** — what problem is being solved and why
2. **Approach** — the chosen strategy and key architectural decisions
3. **Files to modify** — exact file paths and line references
4. **Step-by-step implementation** — ordered, concrete steps
5. **Todo list** — checkboxes (`- [ ]`) for each discrete action
6. **Verification** — how to test that the implementation is correct

When you are satisfied with the plan, tell the user to run `/exit-plan` to begin implementation."""

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
        self.tracker = SessionTracker(model=config.model, thread_id=config.thread_id)
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
            for iteration in range(self.config.max_iterations):
                self.callbacks.on_iteration(iteration + 1, self.config.max_iterations)

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
                    self.tracker.finish(raw_messages=self._messages)
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

        # max iterations hit — ask for a summary
        summary_msg = "Max iterations reached. Summarize what you have done so far."
        self._messages.append({"role": "user", "content": summary_msg})
        self.tracker.record_user(summary_msg)
        self.callbacks.on_api_call(list(self._messages))
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=self._messages,
            **(dict(extra_body=self._reasoning_extra) if self._reasoning_extra else {}),
        )
        _final_msg = response.choices[0].message
        _final_reasoning = _extract_reasoning(_final_msg)
        if _final_reasoning:
            self.callbacks.on_reasoning(_final_reasoning)
        final = _final_msg.content or ""
        self.tracker.record_assistant(final, response.usage, [])
        self.tracker.finish(raw_messages=self._messages)
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
        self.callbacks.on_done(final)
        return final
