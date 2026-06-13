from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import openai

from agent.prompts import load_prompt, load_main_system_prompt, load_soul
from agent.registry import ToolRegistry
from agent.session import SessionTracker, ToolCallRecord
from agent.skills import Skill, SkillLoader
from tools.compact import CompactTool, CompactionResult
from tools.complete_plan import COMPLETE_PLAN_SENTINEL
from tools.plan_mode import ENTER_PLAN_MODE_SENTINEL, EXIT_PLAN_MODE_SENTINEL
from tools.reload_skills import RELOAD_SKILLS_SENTINEL
from tools.switch_model import parse_switch_sentinel

TASK_END_FLAG = "<<TASK_END>>"           # legacy alias — still recognised
AWAIT_USER_FLAG = "<<END_OF_RESPONSE>>"


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


def _format_reload_notification(
    total: int,
    added: set[str],
    removed: set[str],
    errors: list[tuple[str, str]],
) -> str:
    lines = [f"[System: Skills reloaded. {total} skill(s) loaded."]
    if added:
        lines.append(f"  New: {', '.join(sorted(added))}")
    if removed:
        lines.append(f"  Removed: {', '.join(sorted(removed))}")
    if errors:
        for path, reason in errors:
            lines.append(f"  Error: {path} — {reason}")
    if not added and not removed and not errors:
        lines.append("  No changes detected.")
    lines.append("]")
    return "\n".join(lines)


CONTINUE_PROMPT = load_prompt("main/continue.md")


@dataclass
class AgentConfig:
    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""  # always set by agent.config_loader.resolve_model_config
    system_prompt: str = ""  # loaded from files at AgentLoop init time if empty
    thread_id: str | None = None
    thinking: str = "none"  # "none" | "low" | "medium" | "high"
    # Compaction (Pi-style)
    context_window: int = 128_000     # model's hard token limit
    reserve_tokens: int = 16_384      # headroom for summary response + next reply
    keep_recent_tokens: int = 20_000  # tail kept verbatim (token budget)
    # Project scope
    project_path: Path = field(default_factory=lambda: Path(".").resolve())
    # Memory root — absolute path to dagi-memory directory.
    # None means "resolve at loop init time to project_path / dagi-memory".
    memory_root: Path | None = None
    # Plan mode
    plan_mode: bool = False
    plan_file: str | None = None  # absolute path to the active plan document
    plan_mode_initiated_by: str = "user"  # "user" | "dagi"
    # Worker model (cheaper LLM for sub-agents); None = use this config as-is
    worker_config: AgentConfig | None = field(default=None)
    # Advanced model (dedicated LLM for plan mode); None = use this config as-is
    advanced_config: AgentConfig | None = field(default=None)
    # Active plan file persisted in system prompt after plan mode exits
    active_plan_file: str | None = None
    # Human-readable label from the config catalog (e.g. "GPT-4o (OpenAI)")
    display_name: str = ""
    # Continuation: max times the harness injects "continue" before giving up
    max_continuations: int = 10
    # Ghost-response retries: how many times to silently retry an API call that
    # returns content=None with zero token usage before surfacing an error.
    null_response_retries: int = 3
    # Transient API error retries: how many times to retry on 429/5xx/connection
    # errors before propagating the exception. Independent of null_response_retries.
    api_error_retries: int = 3
    # Send cache_prompt: true in extra_body — enables prompt caching on OpenRouter.
    cache_prompt: bool = False
    # bash_backend: previously controlled whether BashTool was replaced by an injected tool.
    # Now a no-op for tool registration — both BashTool and any injected tool are always
    # registered. Kept for config file backwards compatibility.
    bash_backend: str = "subprocess"
    # Accessible tools: None = all tools available; list = only named tools registered.
    tools: list[str] | None = None
    # Sandbox mode: when True, file tools have no path restrictions (allowed_roots=None).
    sandbox_mode: bool = False


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
    on_model_switch:   Callable[[str, str], None]               = field(default=lambda f, t: None)
    on_ask_user:       Callable[[str, list, "float | None"], str] = field(
        default=lambda question, options, timeout: next(
            (o["label"] for o in options if o.get("recommended")),
            options[0]["label"] if options else "",
        )
    )
    on_emote:          Callable[[str], None] | None              = None
    # Factory for subagent stdout relay: takes subagent_type, returns per-event callback.
    # None in headless / CLI mode — subagent output is not relayed.
    on_subagent_event_factory: Callable[[str], Callable[[str], None]] | None = None
    # Pause-on-error: when True, transient API errors that exhaust retries pause the loop
    # instead of raising. The TUI sets this True and wires on_pause to re-enable input.
    # CLI and subagents leave it False so existing raise behaviour is fully preserved.
    on_pause:       Callable[[], None] = field(default=lambda: None)
    supports_pause: bool               = False


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
        _bash_tool: "object | None" = None,
    ):
        from agent.tools import create_tool_registry
        from uuid import uuid4

        self.callbacks = callbacks or AgentCallbacks()
        dagi_root = Path(__file__).parent.parent

        # Stash injected bash tool so plan-mode rebuilds can restore it
        self._injected_bash_tool = _bash_tool

        # ── Create tracker first so sub-agent tools can reference it ─────────
        if _tracker is not None:
            self.tracker = _tracker
        elif _parent_tracker is not None:
            self.tracker = _parent_tracker.child_tracker(_subagent_id or uuid4().hex)
        else:
            self.tracker = SessionTracker(
                model=config.model,
                thread_id=config.thread_id,
                logs_dir=config.project_path / ".dagi" / "logs",
            )

        self._effective_memory_root = (
            config.memory_root if config.memory_root is not None
            else config.project_path / "dagi-memory"
        ).resolve()

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
                allowed_roots=[dagi_root, config.project_path, self._effective_memory_root],
                skill_roots=skill_roots,
                plan_mode=config.plan_mode,
                plan_file=Path(config.plan_file) if config.plan_file else None,
                plan_mode_initiated_by=config.plan_mode_initiated_by,
                config=config,
                callbacks=self.callbacks,
                tracker=self.tracker,
                memory_root=self._effective_memory_root,
                bash_tool=_bash_tool,
            )

        # ── Build system prompt ───────────────────────────────────────────
        readme_path = (dagi_root / "README.md").resolve()
        tools_and_skills_section = _format_tools_and_skills(self.registry, self.skills)
        system_prompt_text = (
            config.system_prompt
            if config.system_prompt
            else load_main_system_prompt(dagi_root, config.project_path)
        )
        prompt = system_prompt_text.format_map(_SafeDict(
            readme_path=readme_path,
            tools_and_skills=tools_and_skills_section,
            cwd=str(config.project_path.resolve()),
            memory_root=str(self._effective_memory_root),
            dagi_root=str(dagi_root.resolve()),
        ))

        # Load preamble: soul (project first, dagi root fallback), then agents.md files
        preamble_parts: list[str] = []
        soul_text = load_soul(dagi_root, config.project_path)
        if soul_text:
            preamble_parts.append(soul_text.strip())
        dagi_agents = dagi_root / ".dagi" / "agents.md"
        if dagi_agents.exists():
            text = dagi_agents.read_text(encoding="utf-8").strip()
            if text:
                preamble_parts.append(text)
        project_agents = config.project_path / ".dagi" / "agents.md"
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
        if soul_text:
            self.system_parts.append({"label": "SOUL.md", "content": soul_text.strip()})
        if dagi_agents.exists():
            self.system_parts.append({"label": ".dagi/agents.md (dagi)", "content": dagi_agents.read_text(encoding="utf-8").strip()})
        if project_agents.exists():
            self.system_parts.append({"label": ".dagi/agents.md (project)", "content": project_agents.read_text(encoding="utf-8").strip()})
        self.system_parts.append({"label": "System Prompt", "content": prompt})

        if initial_messages:
            # multi-turn: continue from existing conversation history
            self._messages = list(initial_messages)
        else:
            self._messages = [{"role": "system", "content": system}]

        self.client = openai.OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.config = config
        # Build extra_body for OpenRouter extensions (reasoning, prompt caching).
        self._extra_body: dict = {}
        if config.thinking and config.thinking.lower() != "none":
            self._extra_body["reasoning"] = {"effort": config.thinking.lower()}
        if config.cache_prompt:
            self._extra_body["cache_prompt"] = True

        # ── Model-tier tracking ───────────────────────────────────────────────
        # Snapshot the five LLM identity fields so "default" tier can always
        # be restored regardless of how many switch_model calls happen.
        self._base_config_snapshot: dict = {
            "model":        config.model,
            "base_url":     config.base_url,
            "api_key":      config.api_key,
            "thinking":     config.thinking,
            "display_name": config.display_name,
        }
        self._current_tier: str = "default"

        self.tracker.record_system(system)

        self.exited_plan_file: str | None = None

        # Reset at the start of each run() call — counts "continue" injections for that task only
        self._continuation_count: int = 0

        # ── Compaction tool (internal-only, not in ToolRegistry) ──────────
        self.compact_tool = CompactTool()
        self.compact_tool.bind(
            self._messages, config, self.client,
            on_compaction=self.callbacks.on_compaction,
            on_summary=self.tracker.record_user,
        )

        # Switch to plan tier immediately when starting in user-initiated plan mode
        if config.plan_mode and config.advanced_config is not None:
            self._handle_switch_model("plan", {"reason": "user-initiated plan mode"})

        # Pause/resume: set = running (default), clear = paused
        self._pause_event = threading.Event()
        self._pause_event.set()

    def pause(self) -> None:
        self._pause_event.clear()

    def inject_and_resume(self, message: str) -> None:
        self._messages.append({"role": "user", "content": message})
        self._pause_event.set()

    def _compact_context(self) -> CompactionResult:
        """Delegates to CompactTool.compact()."""
        return self.compact_tool.compact()

    def run(self, task: str) -> str:
        if task.strip().lower() == "/reload":
            added, removed, errors = self._rebuild_for_reload()
            notification = _format_reload_notification(len(self.skills), added, removed, errors)
            self._messages.append({"role": "system", "content": notification})
            self.callbacks.on_assistant_text(notification)
            return notification

        self._messages.append({"role": "user", "content": task})
        self.tracker.record_user(task)
        self._continuation_count = 0

        try:
            iteration = 0
            while True:
                iteration += 1
                self.callbacks.on_iteration(iteration)
                self._pause_event.wait()  # blocks here when paused; instant no-op otherwise

                # ── API call with retry ────────────────────────────────────
                # Retries on two classes of failure:
                # 1. Transient API errors (429, 500, 502, 503, connection,
                #    timeout) — exponential backoff, separate counter.
                # 2. Ghost responses (HTTP 200, content=None, usage=None) —
                #    instant retry, separate counter.
                _TRANSIENT_CODES = (429, 500, 502, 503)
                _null_retries = 0
                _error_retries = 0
                _paused_on_error = False
                while True:
                    self.callbacks.on_api_call(list(self._messages))
                    try:
                        response = self.client.chat.completions.create(
                            model=self.config.model,
                            messages=self._messages,
                            tools=self.registry.get_openai_tools_list(),
                            parallel_tool_calls=False,
                            **(dict(extra_body=self._extra_body) if self._extra_body else {}),
                        )
                    except (openai.APIConnectionError, openai.APITimeoutError):
                        _error_retries += 1
                        if _error_retries >= self.config.api_error_retries:
                            if self.callbacks.supports_pause:
                                self.callbacks.on_assistant_text(
                                    f"[Connection error — all {_error_retries} retries failed. "
                                    "Session paused. Send a message to retry.]"
                                )
                                self.callbacks.on_pause()
                                self.pause()
                                _paused_on_error = True
                                break
                            raise
                        delay = min(2 ** _error_retries, 60)
                        self.callbacks.on_assistant_text(
                            f"[Connection error. Retrying in {delay}s "
                            f"({_error_retries}/{self.config.api_error_retries})...]"
                        )
                        time.sleep(delay)
                        continue
                    except openai.APIStatusError as exc:
                        if exc.status_code not in _TRANSIENT_CODES:
                            raise
                        _error_retries += 1
                        if _error_retries >= self.config.api_error_retries:
                            if self.callbacks.supports_pause:
                                self.callbacks.on_assistant_text(
                                    f"[Server error {exc.status_code} — all {_error_retries} retries failed. "
                                    "Session paused. Send a message to retry.]"
                                )
                                self.callbacks.on_pause()
                                self.pause()
                                _paused_on_error = True
                                break
                            raise
                        delay = min(2 ** _error_retries, 60)
                        self.callbacks.on_assistant_text(
                            f"[Server error {exc.status_code}. Retrying in {delay}s "
                            f"({_error_retries}/{self.config.api_error_retries})...]"
                        )
                        time.sleep(delay)
                        continue

                    message = response.choices[0].message
                    _prompt_tok = getattr(response.usage, "prompt_tokens", 0) or 0
                    _is_ghost = (
                        not message.tool_calls
                        and not (message.content or "").strip()
                        and _prompt_tok == 0
                    )
                    if not _is_ghost:
                        break  # valid response — proceed
                    _null_retries += 1
                    if _null_retries >= self.config.null_response_retries:
                        error_msg = (
                            f"Error: model returned a null response "
                            f"{_null_retries} time(s) in a row. "
                            "Check your model endpoint and retry your task."
                        )
                        self.callbacks.on_error(Exception(error_msg))
                        return error_msg
                    # else: discard ghost, retry with identical context
                # ─────────────────────────────────────────────────────────────

                if _paused_on_error:
                    continue  # restart outer loop → _pause_event.wait() will block

                _reasoning = _extract_reasoning(message)
                if _reasoning:
                    self.callbacks.on_reasoning(_reasoning)

                tool_records: list[ToolCallRecord] = []

                if not message.tool_calls:
                    result = message.content or ""

                    # Store assistant turn. Use result (never None) so that _messages
                    # stays well-formed for all subsequent API calls.
                    self._messages.append({"role": "assistant", "content": result})
                    _thinking_tok = (
                        getattr(getattr(response.usage, "completion_tokens_details", None), "reasoning_tokens", None)
                        or 0
                    )
                    self.callbacks.on_token_update(
                        _prompt_tok,
                        getattr(response.usage, "completion_tokens", 0) or 0,
                        getattr(response.usage, "cost", None),
                        _thinking_tok,
                    )
                    self.tracker.record_assistant(message.content, response.usage, tool_records)

                    # Check for either exit flag (TASK_END_FLAG kept as legacy alias)
                    _exit_flag = (
                        AWAIT_USER_FLAG if AWAIT_USER_FLAG in result else
                        TASK_END_FLAG   if TASK_END_FLAG   in result else
                        None
                    )
                    if _exit_flag:
                        clean = result.replace(_exit_flag, "").strip()
                        self.callbacks.on_assistant_text(clean)
                        self.callbacks.on_done(clean)
                        return clean

                    # Task not complete — inject "continue" and keep looping
                    self.callbacks.on_assistant_text(result)
                    if self._continuation_count >= self.config.max_continuations:
                        self.callbacks.on_done(result)
                        return result
                    self._continuation_count += 1
                    self._messages.append({"role": "user", "content": CONTINUE_PROMPT})
                    continue  # next while True iteration

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
                    if isinstance(result, str) and result.startswith(ENTER_PLAN_MODE_SENTINEL):
                        result = self._handle_enter_plan_mode(json.loads(tc.function.arguments))
                    elif result == EXIT_PLAN_MODE_SENTINEL:
                        result = self._handle_exit_plan_mode(json.loads(tc.function.arguments))
                    elif result == COMPLETE_PLAN_SENTINEL:
                        result = self._handle_complete_plan()
                    elif result == RELOAD_SKILLS_SENTINEL:
                        added, removed, errors = self._rebuild_for_reload()
                        result = _format_reload_notification(len(self.skills), added, removed, errors)
                        self._messages.append({"role": "system", "content": result})
                    else:
                        _switch_target = parse_switch_sentinel(result)
                        if _switch_target is not None:
                            result = self._handle_switch_model(_switch_target, json.loads(tc.function.arguments))
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
        mode = args.get("mode", "interactive")
        interactive = mode != "autonomous"
        dagi_root = Path(__file__).parent.parent
        plans_dir = self.config.project_path / ".dagi" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_dir = plans_dir / f"plan_{ts}"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text(
            "# Plan: \n\n"
            "## Context\n\n\n"
            "## Approach\n\n\n"
            "## Files to Modify\n\n\n"
            "## Subtasks\n\n"
            "### Subtask 1: [ ] \n"
            "**Goal:** \n"
            "**Requirements:**\n"
            "- \n"
            "**Acceptance Criteria:**\n"
            "- \n"
            "#### Tests\n"
            "<!-- Filled by main agent before executing this subtask — do NOT write tests here -->\n\n"
            "## Notes\n\n"
            "## Verification\n\n",
            encoding="utf-8",
        )

        self._handle_switch_model("plan", {"reason": "entering plan mode"})
        to_name = self.config.display_name or self.config.model

        self.callbacks.on_assistant_text(
            f"Entering plan mode — switching to advanced model ({to_name}).\n\n"
            f"**Plan file:** `{plan_file}`\n\n**Mode:** {mode}"
        )

        self._rebuild_for_plan_mode(dagi_root, plan_file, interactive=interactive)

        return (
            f"Plan mode activated ({mode} mode). Advanced model: {to_name}.\n\n"
            f"Plan file: {plan_file}\n\n"
            f"Tools restricted to: read, grep, find, write/edit (plan file only), "
            f"web_research, skill, run_skill_script, ask_user, show_plan, exit_plan_mode."
        )

    def _handle_exit_plan_mode(self, args: dict) -> str:
        saved_plan = self.config.plan_file
        dagi_root = Path(__file__).parent.parent
        self._handle_switch_model("default", {"reason": "plan complete, returning to normal mode"})
        self.config.active_plan_file = saved_plan
        self.exited_plan_file = saved_plan
        self._rebuild_for_normal_mode(dagi_root)
        if saved_plan and _is_plan_empty(Path(saved_plan)):
            return (
                "The plan document is empty. "
                "Stop immediately and ask the user for further directions "
                "before doing anything else."
            )
        try:
            plan_contents = Path(saved_plan).read_text(encoding="utf-8")
        except Exception:
            plan_contents = "(plan file could not be read)"
        return (
            f"Plan mode exited. Full tools restored. Plan file: {saved_plan}\n\n"
            f"{plan_contents}"
        )

    def _handle_complete_plan(self) -> str:
        cleared = self.config.active_plan_file
        self.config.active_plan_file = None
        self._rebuild_for_normal_mode(Path(__file__).parent.parent)
        return (
            f"Active plan cleared (was: {cleared}). "
            "Handoffs will now go to .dagi/handoffs/. "
            "The plan document is preserved on disk — reference it by path if needed."
        )

    def _handle_switch_model(self, target: str, args: dict) -> str:
        """Switch the active LLM tier in-place without changing the tool registry."""
        reason = args.get("reason", "")

        if target == self._current_tier:
            return (
                f"Already on the '{target}' tier "
                f"({self.config.display_name or self.config.model}) — no switch needed."
            )

        from_name = self.config.display_name or self.config.model

        if target == "plan":
            tier_cfg = self.config.advanced_config
            if tier_cfg is None:
                return (
                    "Cannot switch to 'advanced' tier: no advanced_model is configured in config.yaml. "
                    "Continuing with the current model."
                )
        elif target == "worker":
            tier_cfg = self.config.worker_config
            if tier_cfg is None:
                return (
                    "Cannot switch to 'worker' tier: no worker_model is configured in config.yaml. "
                    "Continuing with the current model."
                )
        elif target == "default":
            snap = self._base_config_snapshot
            self.config.model        = snap["model"]
            self.config.base_url     = snap["base_url"]
            self.config.api_key      = snap["api_key"]
            self.config.thinking     = snap["thinking"]
            self.config.display_name = snap["display_name"]
            tier_cfg = None
        else:
            return f"Unknown model tier '{target}'. Valid values: plan, default, worker."

        if tier_cfg is not None:
            self.config.model        = tier_cfg.model
            self.config.base_url     = tier_cfg.base_url
            self.config.api_key      = tier_cfg.api_key
            self.config.thinking     = tier_cfg.thinking
            self.config.display_name = tier_cfg.display_name

        self.client = openai.OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)

        self._extra_body = {}
        if self.config.thinking and self.config.thinking.lower() != "none":
            self._extra_body["reasoning"] = {"effort": self.config.thinking.lower()}
        if self.config.cache_prompt:
            self._extra_body["cache_prompt"] = True

        self.compact_tool.bind(
            self._messages, self.config, self.client,
            on_compaction=self.callbacks.on_compaction,
            on_summary=self.tracker.record_user,
        )

        self._current_tier = target
        to_name = self.config.display_name or self.config.model
        self.callbacks.on_model_switch(from_name, to_name)

        return f"Switched to '{target}' tier: {to_name}. Reason: {reason}"

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
            allowed_roots=[dagi_root, self.config.project_path, self._effective_memory_root],
            skill_roots=skill_roots,
            plan_mode=False,
            plan_file=None,
            plan_mode_initiated_by="user",
            config=self.config,
            callbacks=self.callbacks,
            tracker=self.tracker,
            bash_tool=self._injected_bash_tool,
        )

        tools_and_skills = _format_tools_and_skills(self.registry, self.skills)
        readme_path = (dagi_root / "README.md").resolve()
        effective_memory_root = (
            self.config.memory_root if self.config.memory_root is not None
            else self.config.project_path / "dagi-memory"
        ).resolve()
        new_system = self.config.system_prompt.format_map(_SafeDict(
            readme_path=readme_path,
            tools_and_skills=tools_and_skills,
            cwd=str(self.config.project_path.resolve()),
            memory_root=str(effective_memory_root),
            dagi_root=str(dagi_root.resolve()),
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
            on_summary=self.tracker.record_user,
        )

    def _rebuild_for_plan_mode(self, dagi_root: Path, plan_file: Path, interactive: bool = True) -> None:
        from agent.tools import create_tool_registry

        initiated_by = "user" if interactive else "dagi"
        self.config.plan_mode = True
        self.config.plan_file = str(plan_file)
        self.config.plan_mode_initiated_by = initiated_by

        skill_roots = [
            dagi_root / ".dagi" / "skills",
            self.config.project_path / ".dagi" / "skills",
        ]
        self.registry = create_tool_registry(
            cwd=self.config.project_path,
            allowed_roots=[dagi_root, self.config.project_path, self._effective_memory_root],
            skill_roots=skill_roots,
            plan_mode=True,
            plan_file=plan_file,
            plan_mode_initiated_by=initiated_by,
            config=self.config,
            callbacks=self.callbacks,
            tracker=self.tracker,
            memory_root=self._effective_memory_root,
        )
        tools_and_skills = _format_tools_and_skills(self.registry, self.skills)
        readme_path = (dagi_root / "README.md").resolve()
        effective_memory_root = (
            self.config.memory_root if self.config.memory_root is not None
            else self.config.project_path / "dagi-memory"
        ).resolve()
        new_system = self.config.system_prompt.format_map(_SafeDict(
            readme_path=readme_path,
            tools_and_skills=tools_and_skills,
            cwd=str(self.config.project_path.resolve()),
            memory_root=str(effective_memory_root),
            dagi_root=str(dagi_root.resolve()),
        ))
        new_system += f"\n\n---\n\nProject root: {self.config.project_path}"
        self._messages[0] = {"role": "system", "content": new_system}
        self.compact_tool.bind(
            self._messages, self.config, self.client,
            on_compaction=self.callbacks.on_compaction,
            on_summary=self.tracker.record_user,
        )

    def _rebuild_for_reload(self) -> tuple[set[str], set[str], list[tuple[str, str]]]:
        """Hot-reload skills from disk, rebuild registry + system prompt preserving current mode.

        Returns (added_names, removed_names, errors) for notification formatting.
        """
        dagi_root = Path(__file__).parent.parent
        skill_roots = [
            dagi_root / ".dagi" / "skills",
            self.config.project_path / ".dagi" / "skills",
        ]

        before_names = {s.name for s in self.skills}
        new_skills, errors = SkillLoader().load_all_with_errors(skill_roots, dagi_root=dagi_root)
        self.skills = new_skills
        after_names = {s.name for s in self.skills}

        if self.config.plan_mode and self.config.plan_file:
            self._rebuild_for_plan_mode(dagi_root, Path(self.config.plan_file))
        else:
            self._rebuild_for_normal_mode(dagi_root)

        return after_names - before_names, before_names - after_names, errors

    def finish(self) -> None:
        """Finalize the session — write session_end to JSONL. Called by the CLI at session end."""
        self.tracker.finish(raw_messages=self._messages)
