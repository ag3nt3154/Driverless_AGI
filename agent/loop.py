from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

import httpx
import openai
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
)

from agent import DAGI_ROOT
from agent._git_branch import create_task_branch, get_current_branch
from agent.prompts import load_prompt, load_main_system_prompt, load_soul
from agent.registry import ToolRegistry
from agent import session_events as sev
from agent.session import SessionTracker, ToolCallRecord
from agent.session_log import InvariantError, SessionLog, is_status_board
from agent.session_store import append_event
from agent.skills import Skill, SkillLoader
from tools.subagent_api import run_subagent
from tools.compact._tail_boundary import compute_tail_boundary, TailBoundary
from tools.update_task_status import UPDATE_TASK_STATUS_SENTINEL
from tools.plan_mode import ENTER_PLAN_MODE_SENTINEL, EXIT_PLAN_MODE_SENTINEL
from tools.reload_skills import RELOAD_SKILLS_SENTINEL
from tools.output_filter import filter_tool_output
from tools.switch_model import parse_switch_sentinel

TASK_END_FLAG = "<<TASK_END>>"           # legacy alias — still recognised
AWAIT_USER_FLAG = "<<END_OF_RESPONSE>>"
WRITE_HANDOFF_SENTINEL = "<<HANDOFF_WRITTEN>>"

_LOOP_SENTINELS = (AWAIT_USER_FLAG, TASK_END_FLAG)


def _escape_sentinels(text: str) -> str:
    """Break loop-control sentinels so they cannot leak from tool results into the
    LLM's message history and cause premature termination on the next turn.

    Replaces '<<' with '< <' in each sentinel — visually similar but won't match
    the substring checks in AgentLoop.run().
    """
    for sentinel in _LOOP_SENTINELS:
        text = text.replace(sentinel, sentinel.replace("<<", "< <"))
    return text


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


def _build_wiki_index_context(memory_root: Path) -> str | None:
    """Read wiki root and section .index.md files; return a formatted context block."""
    wiki_root = memory_root / "wiki"
    root_index = wiki_root / ".index.md"
    if not root_index.exists():
        return None
    parts = [root_index.read_text(encoding="utf-8")]
    for section in ("projects", "knowledge"):
        section_index = wiki_root / section / ".index.md"
        if section_index.exists():
            parts.append(section_index.read_text(encoding="utf-8"))
    return "[WIKI INDEX]\n" + "\n\n---\n\n".join(parts) + "\n[END WIKI INDEX]"


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
class CompactionResult:
    did_compact: bool
    generation: int = 0
    summary_content: str | None = None
    removed_count: int = 0


_NO_COMPACTION = CompactionResult(did_compact=False)


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
    # Branch the user was on before entering plan mode — used for checkout-back at task end
    previous_branch: str | None = None
    # Human-readable label from the config catalog (e.g. "GPT-4o (OpenAI)")
    display_name: str = ""
    # Resolved model ID from the catalog (e.g. "gpt-4o-openai"). Set by resolve_model_config.
    # Used by the TUI to update sidebar state when /wd triggers a project switch.
    model_id: str = ""
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
    # Streaming: consume the API response as a chunk stream, firing per-delta
    # callbacks. Dataclass default is False so direct AgentConfig() construction
    # (tests, benchmarks) keeps the blocking path; config_loader defaults the
    # config-file value to True, so all real entry points stream unless
    # .dagi/config.yaml sets `stream: false` (globally or per-model).
    stream: bool = False
    # bash_backend: previously controlled whether BashTool was replaced by an injected tool.
    # Now a no-op for tool registration — both BashTool and any injected tool are always
    # registered. Kept for config file backwards compatibility.
    bash_backend: str = "subprocess"
    # Accessible tools: None = all tools available; list = only named tools registered.
    tools: list[str] | None = None
    # Disabled tools: tools to remove from the registry even when `tools` is None.
    disabled_tools: list[str] | None = None
    # Sandbox mode: when True, file tools have no path restrictions (allowed_roots=None).
    sandbox_mode: bool = False
    # Benchmark/sandbox environment preamble injected at the TOP of the system prompt.
    system_prompt_preamble: str = ""
    # OpenRouter provider routing: ordered list of provider slugs to try in sequence
    # (e.g. ["Anthropic", "Together"]). None means use OpenRouter's default load balancing.
    # Sent as extra_body["provider"]["order"] — ignored by non-OpenRouter endpoints.
    provider_order: list[str] | None = None
    # Scheduler: override the ask_user timeout (seconds). None = use default (300s).
    # Set to 60 by the scheduler runner for fully autonomous execution.
    ask_user_timeout: int | None = None
    # External service URLs (e.g. {"doc_converter": "http://localhost:8100"}).
    # Loaded from the `services` block in .dagi/config.yaml.
    services: dict[str, str] = field(default_factory=dict)
    # Active Python environment detected at startup (e.g. "conda:dagi" or "venv:/path")
    # Set by config_loader._detect_python_env()
    python_env: str = ""


@dataclass
class AgentCallbacks:
    """Optional observer hooks for the agent loop. All default to no-ops so the
    CLI path pays zero cost. The UI wires these to queue events for live updates."""
    on_tool_start:     Callable[[str, str, str], None]          = field(default=lambda n, d, a: None)
    on_tool_end:       Callable[[str, str], None]               = field(default=lambda n, r: None)
    on_assistant_text: Callable[[str], None]                    = field(default=lambda t: None)
    on_token_update:   Callable[[int, int, float | None, int, int], None] = field(default=lambda i, o, c, t, ca=0: None)
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
    on_emote:          Callable[[str, str], None] | None         = None
    # Factory for subagent stdout relay: takes subagent_type, returns per-event callback.
    # None in headless / CLI mode — subagent output is not relayed.
    on_subagent_event_factory: Callable[[str], Callable[[str], None]] | None = None
    # Pause-on-error: when True, transient API errors that exhaust retries pause the loop
    # instead of raising. The TUI sets this True and wires on_pause to re-enable input.
    # CLI and subagents leave it False so existing raise behaviour is fully preserved.
    on_pause:       Callable[[], None] = field(default=lambda: None)
    supports_pause: bool               = False
    # Fired when the harness injects a "continue" prompt because the response had no exit flag.
    # Args: (current_count, max_continuations)
    on_continue_injected: Callable[[int, int], None] = field(default=lambda cur, mx: None)
    # Fired when a plan is rendered for interactive review (ShowPlanTool, interactive mode only).
    on_plan_shown: Callable[[], None] = field(default=lambda: None)
    # Streaming (config.stream=True only). on_stream_start fires before the first
    # chunk, on_stream_end always fires when consumption stops (even on error).
    # Deltas carry the raw incremental string for that chunk. The existing
    # on_assistant_text / on_reasoning still fire once afterward with full text.
    on_stream_start:         Callable[[], None]    = field(default=lambda: None)
    on_stream_end:           Callable[[], None]    = field(default=lambda: None)
    on_assistant_text_delta: Callable[[str], None] = field(default=lambda t: None)
    on_reasoning_delta:      Callable[[str], None] = field(default=lambda t: None)


def _extract_reasoning(message) -> str:
    """Get reasoning text from the response message, trying SDK attr then model_extra."""
    text = getattr(message, "reasoning_content", None) or ""
    if not text:
        extras = getattr(message, "model_extra", None) or {}
        text = extras.get("reasoning") or extras.get("reasoning_content") or ""
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
        dagi_root = DAGI_ROOT

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

        self.log = SessionLog()
        if hasattr(self.tracker, "_path"):
            _events_path = self.tracker._path.with_suffix(".events.jsonl")
            self.log.on_append = lambda event: append_event(_events_path, event)

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
                session_log=self.log,
            )

        self.config = config
        # ── Build system prompt ───────────────────────────────────────────
        system = self._assemble_system_string(dagi_root)
        self.system_parts: list[dict]  # populated by _assemble_system_string

        self._skip_slug_generation: bool = bool(initial_messages)
        #: Derived cache of [header] + log.derive_messages(). Never mutated
        #: directly — see _sync_messages. Created empty because _seed_from_messages
        #: below is what actually reconstitutes a resumed conversation.
        self._messages: list[dict] = []

        # The log is the source of truth; _messages is a derived cache of it.
        # See docs/superpowers/specs/2026-08-16-session-event-log-design.md
        # (self.log is initialized earlier, before create_tool_registry, so it
        # can be forwarded to subagent tools at construction time.)
        #: Last rendered plan status board. Ephemeral request state — see
        #: _refresh_dynamic_context. Empty string means "nothing rendered yet".
        self._board: str = ""
        self._emit_header(system, "resume" if initial_messages else "initial")
        if initial_messages:
            self._seed_from_messages(initial_messages)
        self._sync_messages()

        self.client = openai.OpenAI(api_key=config.api_key, base_url=config.base_url)
        # Build extra_body for OpenRouter extensions (reasoning, prompt caching, provider routing).
        self._extra_body: dict = {}
        if config.thinking and config.thinking.lower() != "none":
            self._extra_body["reasoning"] = {"effort": config.thinking.lower()}
        if config.cache_prompt:
            self._extra_body["cache_prompt"] = True
        if config.provider_order:
            self._extra_body["provider"] = {"order": config.provider_order}

        # ── Model-tier tracking ───────────────────────────────────────────────
        # Snapshot the six LLM identity fields so "default" tier can always
        # be restored regardless of how many switch_model calls happen.
        self._base_config_snapshot: dict = {
            "model":          config.model,
            "base_url":       config.base_url,
            "api_key":        config.api_key,
            "thinking":       config.thinking,
            "display_name":   config.display_name,
            "provider_order": config.provider_order,
        }
        self._current_tier: str = "default"

        self.tracker.record_system(system)

        # Reset at the start of each run() call — counts "continue" injections for that task only
        self._continuation_count: int = 0
        self._last_prompt_tokens: int = 0
        self._compaction_generation: int = 0

        # Switch to plan tier immediately when starting in user-initiated plan mode
        if config.plan_mode and config.advanced_config is not None:
            self._handle_switch_model("plan", {"reason": "user-initiated plan mode"})

        # Pause/resume: set = running (default), clear = paused
        self._pause_event = threading.Event()
        self._pause_event.set()

    def pause(self) -> None:
        self._pause_event.clear()

    def inject_and_resume(self, message: str) -> None:
        self._log_user_message("user", message, "inject")
        self._pause_event.set()

    def _compact_context(self) -> CompactionResult:
        """Delegates to compact(). Failures are non-fatal — the session continues
        with un-compacted messages rather than crashing."""
        try:
            return self.compact()
        except Exception as exc:
            self.callbacks.on_assistant_text(
                f"[Warning: context compaction failed — {exc}. Continuing with full context.]"
            )
            return _NO_COMPACTION

    def _consume_stream(self, stream) -> "tuple[SimpleNamespace, object | None]":
        """Accumulate a chat-completions chunk stream into the same
        (message, usage) shapes the blocking path produces, firing per-delta
        callbacks as chunks arrive.

        Returned message mimics response.choices[0].message: .content,
        .tool_calls (list of .id/.function.name/.function.arguments, or None),
        .reasoning_content (for _extract_reasoning). usage is the provider's
        trailing usage object, or None if it never arrived — downstream
        getattr(usage, ..., 0) patterns already tolerate None.
        """
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        usage = None
        self.callbacks.on_stream_start()
        try:
            for chunk in stream:
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage
                if not getattr(chunk, "choices", None):
                    continue  # usage-only trailing chunk has choices=[]
                delta = chunk.choices[0].delta
                if delta is None:
                    continue

                piece = getattr(delta, "content", None)
                if piece:
                    content_parts.append(piece)
                    self.callbacks.on_assistant_text_delta(piece)

                # OpenRouter sends `reasoning`; DeepSeek sends `reasoning_content`;
                # SDK may park unknown keys in model_extra.
                r = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                if not r:
                    extras = getattr(delta, "model_extra", None) or {}
                    r = extras.get("reasoning") or extras.get("reasoning_content") or ""
                if r:
                    reasoning_parts.append(r)
                    self.callbacks.on_reasoning_delta(r)

                for tc in getattr(delta, "tool_calls", None) or []:
                    acc = tool_calls_acc.setdefault(
                        tc.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if getattr(tc, "id", None):
                        acc["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            acc["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            acc["arguments"] += fn.arguments
        finally:
            self.callbacks.on_stream_end()

        tool_calls = [
            SimpleNamespace(
                id=acc["id"],
                type="function",
                function=SimpleNamespace(name=acc["name"], arguments=acc["arguments"]),
            )
            for _idx, acc in sorted(tool_calls_acc.items())
        ] or None
        message = SimpleNamespace(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            reasoning_content="".join(reasoning_parts) or None,
        )
        return message, usage

    _SLUG_SYSTEM = (
        "Generate a 3-5 word snake_case slug summarising this task. "
        "Reply with ONLY the slug, nothing else."
    )

    def _generate_session_slug(self, first_message: str) -> str | None:
        """LLM side-call to generate a session name slug. Returns None on failure."""
        try:
            resp = self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": self._SLUG_SYSTEM},
                    {"role": "user", "content": first_message[:500]},
                ],
                max_tokens=30,
            )
            slug = (resp.choices[0].message.content or "").strip()
            return slug if slug else None
        except Exception:
            return None

    def _close_turn(self, turn: int, reason: dict) -> None:
        """Close the open turn, if one is open. Idempotent by design.

        run() has several return paths; each closes its own turn explicitly,
        and the finally-guard catches any path added later without one.
        """
        if self.log.open_turn is None:
            return
        if self.log.open_step is not None:
            self.log.append(sev.STEP_END, {"turn": turn, "step": self.log.open_step})
        self.log.append(sev.TURN_END, {"turn": turn, "reason": reason})

    def _log_user_message(self, role: str, content, source: str) -> None:
        """Append one user/message surface event.

        `role` is durable: wiki context and skill-reload notices are
        role="system" but ride this event type, because they are ordinary
        model-visible conversation content. `source` is the semantic channel
        that tells the three apart.

        `step` is 0 for messages that enter the turn before its first step.
        """
        self.log.append(
            sev.USER_MESSAGE,
            {
                "turn": self.log.open_turn,
                "step": self.log.open_step or 0,
                "role": role,
                "content": content,
                "source": source,
            },
            surface_op="append",
        )
        self._sync_messages()

    def _tools_fingerprint(self) -> tuple[list[str], str]:
        """Sorted tool names plus a stable digest of their full schemas."""
        schemas = self.registry.get_openai_tools_list()
        names = sorted(s["function"]["name"] for s in schemas)
        blob = json.dumps(schemas, sort_keys=True, ensure_ascii=False)
        return names, hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _emit_header(self, system: str, reason: str) -> None:
        """Record the request envelope. Log-only — never a surface node."""
        names, digest = self._tools_fingerprint()
        self.log.append(
            sev.REQUEST_HEADER,
            {
                "system": system,
                "reason": reason,
                "model": self.config.model,
                "tool_names": names,
                "tools_digest": digest,
            },
        )

    def _header_message(self) -> dict:
        """The system message, rebuilt from the latest header event."""
        header = self.log.latest_header()
        if header is None:
            raise InvariantError("no request/header has been logged")
        return {"role": "system", "content": header["system"]}

    def _build_request_messages(self) -> list[dict]:
        """The exact message list sent to the provider.

        Envelope header first, conversation next, ephemeral board last.
        Returns a fresh list: callers (including on_api_call observers) must
        not be able to mutate loop state through it.
        """
        messages = [self._header_message()]
        messages.extend(self._messages[1:])
        if self._board:
            messages.append({"role": "system", "content": self._board})
        return messages

    def _collect_steps(self) -> list[tuple[int, int]]:
        """Return chronological list of (turn, step) pairs from the main branch log."""
        steps: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for event in self.log.events:
            if event.branch != "main":
                continue
            if event.type == sev.STEP_START:
                key = (event.data["turn"], event.data["step"])
                if key not in seen:
                    seen.add(key)
                    steps.append(key)
        return steps

    def _find_surface_index_for_step(self, target: tuple[int, int]) -> int:
        """Return the surface node index of the first event in the given (turn, step)."""
        t_turn, t_step = target
        event_map = {e.seq: e for e in self.log.events}
        for idx, seq in enumerate(self.log.surface.nodes):
            event = event_map.get(seq)
            if event is None:
                continue
            if event.data.get("turn") == t_turn and event.data.get("step") == t_step:
                return idx
        raise ValueError(f"step ({t_turn}, {t_step}) not found on surface")

    def _log_compaction(self, result: CompactionResult, tail_first_step: tuple[int, int]) -> None:
        """Record a subagent compaction as a surface replace.

        Shadows all surface nodes before the tail's first step with a single
        CONTEXT_COMPACTION event containing the summary.
        """
        if not result.did_compact:
            return
        nodes = self.log.surface.nodes
        if not nodes:
            return

        try:
            tail_surface_idx = self._find_surface_index_for_step(tail_first_step)
        except ValueError:
            raise InvariantError(
                f"tail step {tail_first_step} not found on surface — "
                f"cannot log compaction"
            )

        lo = 0
        hi = tail_surface_idx - 1

        if hi < lo:
            return  # nothing to shadow (tail starts at position 0)
        if hi >= len(nodes):
            raise InvariantError(
                f"compaction span [{lo}, {hi}] is outside surface of "
                f"{len(nodes)} node(s)"
            )

        self.log.append(
            sev.CONTEXT_COMPACTION,
            {
                "summary": result.summary_content,
                "removed": result.removed_count,
                "generation": result.generation,
            },
            surface_op=("replace", nodes[lo], nodes[hi]),
            source_seqs=nodes[lo:hi + 1],
        )
        self._sync_messages()

    def compact(self, force: bool = False) -> CompactionResult:
        """Compact context by spawning a compact subagent.

        The subagent inherits the parent's warm KV-cache prefix via
        spec_for_branch, summarizes the conversation middle, and returns
        the summary as its handoff.

        Exceptions propagate — callers that want them swallowed use
        _compact_context.
        """
        steps = self._collect_steps()
        if not steps:
            return _NO_COMPACTION

        boundary = compute_tail_boundary(
            steps=steps,
            prompt_tokens=self._last_prompt_tokens,
            keep_recent_tokens=self.config.keep_recent_tokens,
        )

        if not boundary.has_middle and not force:
            return _NO_COMPACTION

        if not boundary.has_middle:
            # forced but nothing to compact (e.g. only 1 step)
            return _NO_COMPACTION

        middle_end = boundary.middle_steps[-1]
        task = (
            f"Summarize all conversation from the beginning through "
            f"turn {middle_end[0]} step {middle_end[1]}. "
            f"Everything after that is the recent tail — do not include "
            f"it in your summary."
        )

        result = run_subagent(
            task=task,
            preset="compact",
            project_path=self.config.project_path,
            parent_log=self.log,
        )

        if not result.is_ok or not result.handoff_text.strip():
            return _NO_COMPACTION

        self._compaction_generation += 1
        summary_content = (
            f"[CONTEXT SUMMARY — conversation compacted "
            f"(generation {self._compaction_generation})]\n\n"
            f"{result.handoff_text}"
        )
        compaction = CompactionResult(
            did_compact=True,
            generation=self._compaction_generation,
            summary_content=summary_content,
            removed_count=len(boundary.middle_steps),
        )
        self._log_compaction(compaction, boundary.tail_steps[0])
        return compaction

    def _sync_messages(self) -> None:
        """Rebuild ``_messages`` from the log, in place."""
        self._messages[:] = [self._header_message(), *self.log.derive_messages()]

    def _seed_one(self, message: Mapping[str, Any]) -> None:
        """Replay one resumed message as its corresponding surface event."""
        coords = {"turn": 0, "step": 0}
        role = message.get("role")
        if role == "assistant":
            self.log.append(
                sev.ASSISTANT_MESSAGE,
                {**coords, "message": dict(message)},
                surface_op="append",
            )
            # The pairing invariant needs these, or the tool messages that
            # follow have nothing to attach to.
            for tc in message.get("tool_calls") or []:
                fn = tc.get("function", {})
                self.log.append(sev.TOOL_CALL, {
                    **coords,
                    "call_id": tc["id"],
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", ""),
                })
        elif role == "tool":
            self.log.append(
                sev.TOOL_RESULT,
                {
                    **coords,
                    "call_id": message["tool_call_id"],
                    "content": message.get("content"),
                    "meta": None,
                },
                surface_op="append",
            )
        else:
            self._log_user_message(role, message.get("content"), "seed")

    def _seed_from_messages(self, messages: Sequence[Mapping[str, Any]]) -> None:
        """Replay a resumed conversation into the log as turn-0 events.

        ``_messages`` is derived from the log, so history that never enters
        the log simply does not exist. Seeded events sit in turn 0 — "before
        this process began" — so ``next_turn()`` still returns 1, and
        ``session/end-seed`` closes the replay so nothing can append into it.

        ``messages[0]`` is skipped: the system prompt is envelope state, and
        it is deliberately re-assembled on resume so that an edited AGENTS.md
        takes effect on the next task.
        """
        self.log.append(sev.TURN_START, {"turn": 0})
        for message in messages[1:]:
            self._seed_one(message)
        self.log.append(sev.TURN_END, {"turn": 0, "reason": sev.reason_completed()})
        self.log.append(sev.END_SEED, {"count": len(messages) - 1})

    def run(self, task: str) -> str:
        if task.strip().lower() == "/reload":
            added, removed, errors = self._rebuild_for_reload()
            notification = _format_reload_notification(len(self.skills), added, removed, errors)
            # A surface event needs an enclosing turn, and /reload short-circuits
            # before the normal one opens — so it gets its own.
            _reload_turn = self.log.next_turn()
            self.log.append(sev.TURN_START, {"turn": _reload_turn})
            self._log_user_message("system", notification, "reload")
            self._close_turn(_reload_turn, sev.reason_completed())
            self.callbacks.on_assistant_text(notification)
            return notification

        _turn = self.log.next_turn()
        self.log.append(sev.TURN_START, {"turn": _turn})

        wiki_ctx = _build_wiki_index_context(self._effective_memory_root)
        if wiki_ctx:
            self._log_user_message("system", wiki_ctx, "wiki")
        self._log_user_message("user", task, "human")
        self.tracker.record_user(task)

        # ── Auto-name session file from first user message ────────────────────
        if not self._skip_slug_generation:
            slug = self._generate_session_slug(task)
            if slug:
                self.tracker.rename_with_slug(slug)

        self._continuation_count = 0

        try:
            iteration = 0
            while True:
                iteration += 1
                self.log.append(sev.STEP_START, {"turn": _turn, "step": iteration})
                self._refresh_dynamic_context()
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
                    _request = self._build_request_messages()
                    self.callbacks.on_api_call(list(_request))
                    try:
                        _create_kwargs = dict(
                            model=self.config.model,
                            messages=_request,
                            tools=self.registry.get_openai_tools_list(),
                            parallel_tool_calls=False,
                            **(dict(extra_body=self._extra_body) if self._extra_body else {}),
                        )
                        if self.config.stream:
                            _stream = self.client.chat.completions.create(
                                stream=True,
                                stream_options={"include_usage": True},
                                **_create_kwargs,
                            )
                            _msg, _usage = self._consume_stream(_stream)
                            response = SimpleNamespace(
                                choices=[SimpleNamespace(message=_msg)], usage=_usage
                            )
                        else:
                            response = self.client.chat.completions.create(**_create_kwargs)
                    except (openai.APIConnectionError, openai.APITimeoutError, httpx.HTTPError):
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
                        self._close_turn(_turn, sev.reason_error(error_msg))
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
                    # DeepSeek thinking mode requires reasoning_content to be echoed back.
                    _asst_msg: dict = {"role": "assistant", "content": result}
                    _rc = _extract_reasoning(message)
                    if _rc:
                        _asst_msg["reasoning_content"] = _rc
                    self.log.append(
                        sev.ASSISTANT_MESSAGE,
                        {"turn": _turn, "step": iteration, "message": _asst_msg},
                        surface_op="append",
                    )
                    self._sync_messages()
                    _thinking_tok = (
                        getattr(getattr(response.usage, "completion_tokens_details", None), "reasoning_tokens", None)
                        or 0
                    )
                    _cached_tok = (
                        getattr(getattr(response.usage, "prompt_tokens_details", None), "cached_tokens", None)
                        or 0
                    )
                    self.callbacks.on_token_update(
                        _prompt_tok,
                        getattr(response.usage, "completion_tokens", 0) or 0,
                        getattr(response.usage, "cost", None),
                        _thinking_tok,
                        _cached_tok,
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
                        self._close_turn(_turn, sev.reason_completed())
                        return clean

                    # Task not complete — inject "continue" and keep looping
                    self.callbacks.on_assistant_text(result)
                    if self._continuation_count >= self.config.max_continuations:
                        self.callbacks.on_done(result)
                        self._close_turn(_turn, sev.reason_max_continuations())
                        return result
                    self._continuation_count += 1
                    self._log_user_message("user", CONTINUE_PROMPT, "continue")
                    self.callbacks.on_continue_injected(
                        self._continuation_count, self.config.max_continuations
                    )
                    self.log.append(sev.STEP_END, {"turn": _turn, "step": iteration})
                    continue  # next while True iteration

                if message.content:
                    self.callbacks.on_assistant_text(message.content)

                # One assistant message with ALL tool_calls (standard OpenAI format).
                # Splitting into per-tool-call assistant messages breaks providers that
                # enforce protocol conformance (e.g. DeepSeek thinking mode).
                _turn_reasoning = _extract_reasoning(message)
                _asst_tc_msg: dict = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in message.tool_calls
                    ],
                }
                if _turn_reasoning:
                    _asst_tc_msg["reasoning_content"] = _turn_reasoning
                self.log.append(
                    sev.ASSISTANT_MESSAGE,
                    {"turn": _turn, "step": iteration, "message": _asst_tc_msg},
                    surface_op="append",
                )
                self._sync_messages()

                _short_circuit = self._dispatch_tool_calls(message, response, tool_records)
                if _short_circuit is not None:
                    self._close_turn(_turn, sev.reason_completed())
                    return _short_circuit

                self._finalize_turn(message, response, tool_records)

                # ── Compaction trigger ────────────────────────────────────────
                _prompt_tok = getattr(response.usage, "prompt_tokens", 0) or 0
                self._last_prompt_tokens = _prompt_tok
                if (
                    self.config.context_window > 0
                    and _prompt_tok > 0
                    and _prompt_tok > self.config.context_window - self.config.reserve_tokens
                ):
                    self._compact_context()
                # ─────────────────────────────────────────────────────────────

                self.log.append(sev.STEP_END, {"turn": _turn, "step": iteration})

        except Exception as e:
            self._close_turn(_turn, sev.reason_error(str(e), type(e).__name__))
            self.callbacks.on_error(e)
            raise
        finally:
            # Defensive: any exit path added later without an explicit close
            # still leaves the log well-formed rather than half-open.
            self._close_turn(_turn, sev.reason_error("turn closed without a reason"))

    def _dispatch_tool_calls(self, message, response, tool_records) -> str | None:
        """Dispatch every tool call in `message`, appending results to _messages.

        Extracted verbatim from `run()`. Returns a non-None string only when
        the write_handoff sentinel fired, in which case `run()` must return
        that value immediately without a further API turn.

        Deferred system messages are appended AFTER all tool results so they
        don't break the assistant→tool pairing that strict providers
        (e.g. DeepSeek) enforce.
        """
        deferred_system_msgs: list[str] = []

        for tc in message.tool_calls:
            tool_obj = self.registry._tools.get(tc.function.name)
            description = tool_obj.description if tool_obj else tc.function.name
            self.callbacks.on_tool_start(tc.function.name, description, tc.function.arguments)
            self.tracker.record_tool_start(tc.function.name, description, tc.function.arguments)

            # Recorded BEFORE execution: a tool/call with no tool/result is a
            # detectable interruption, which Phase 4 crash repair depends on.
            self.log.append(
                sev.TOOL_CALL,
                {
                    "turn": self.log.open_turn,
                    "step": self.log.open_step,
                    "call_id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,  # raw, unparsed
                },
            )
            args = json.loads(tc.function.arguments)
            result = self.registry.dispatch(tc.function.name, args)
            if (
                isinstance(result, str)
                and WRITE_HANDOFF_SENTINEL in result
                and tc.function.name == "write_handoff"
            ):
                return self._handle_write_handoff(
                    tc, result, description, tool_records, (message, response)
                )
            if isinstance(result, str) and result.startswith(ENTER_PLAN_MODE_SENTINEL):
                result = self._handle_enter_plan_mode(args)
            elif result == EXIT_PLAN_MODE_SENTINEL:
                result = self._handle_exit_plan_mode(args)
            elif isinstance(result, str) and UPDATE_TASK_STATUS_SENTINEL in result:
                result = self._handle_all_tasks_resolved()
            elif result == RELOAD_SKILLS_SENTINEL:
                added, removed, errors = self._rebuild_for_reload()
                result = _format_reload_notification(len(self.skills), added, removed, errors)
                deferred_system_msgs.append(result)
            else:
                if isinstance(result, str):
                    _switch_target = parse_switch_sentinel(result)
                    if _switch_target is not None:
                        result = self._handle_switch_model(_switch_target, args)
            self._bookkeep_tool_call(tc, result, description, tool_records)

        for _sys_content in deferred_system_msgs:
            self._log_user_message("system", _sys_content, "reload")
        return None

    def _bookkeep_tool_call(
        self,
        tc: ChatCompletionMessageFunctionToolCall,
        result,
        description: str,
        tool_records: list[ToolCallRecord],
    ) -> str:
        """Filter, log, and record a single tool call's result, appending its
        tool message to self._messages. Shared by the normal per-tool-call
        dispatch loop and the `_handle_write_handoff` short-circuit path so
        the two can't drift (e.g. the list-safety conversion below must
        apply to both). Returns the full (unfiltered) result string.
        """
        # ── Output filter ────────────────────────────────────────
        context_result, full_str = filter_tool_output(
            result, self.config.reserve_tokens, Path(self.config.project_path)
        )
        if context_result is not result:
            # Filtering fired — warn the user via the assistant text stream
            self.callbacks.on_assistant_text(
                f"[output filter] Tool result was large and has been truncated. "
                f"Full output saved under "
                f"{Path(self.config.project_path) / '.dagi' / 'hash_cache' / 'tool_output'}."
            )
        # ─────────────────────────────────────────────────────────
        result_str = (
            context_result if isinstance(context_result, str)
            else "__list__:" + json.dumps(context_result)
        )
        self.callbacks.on_tool_end(tc.function.name, result_str)   # filtered
        self.tracker.record_tool_end(tc.function.name, full_str)    # full (JSONL)

        tool_records.append(ToolCallRecord(
            name=tc.function.name,
            description=description,
            input=tc.function.arguments,
            result=full_str,                                        # full (JSONL)
        ))
        _tool_content = (
            _escape_sentinels(context_result)
            if isinstance(context_result, str)
            else context_result
        )
        self.log.append(
            sev.TOOL_RESULT,
            {
                "turn": self.log.open_turn,
                "step": self.log.open_step,
                "call_id": tc.id,
                "content": _tool_content,
                "meta": None,
            },
            surface_op="append",
        )
        self._sync_messages()
        return full_str

    def _finalize_turn(self, message, response, tool_records: list[ToolCallRecord]) -> None:
        """Record the assistant turn and emit the token-usage callback.

        Shared by the end of the normal per-tool-call loop and the
        `_handle_write_handoff` short-circuit path.
        """
        self.tracker.record_assistant(message.content, response.usage, tool_records)
        _thinking_tok = (
            getattr(getattr(response.usage, "completion_tokens_details", None), "reasoning_tokens", None)
            or 0
        )
        _cached_tok = (
            getattr(getattr(response.usage, "prompt_tokens_details", None), "cached_tokens", None)
            or 0
        )
        self.callbacks.on_token_update(
            getattr(response.usage, "prompt_tokens", 0) or 0,
            getattr(response.usage, "completion_tokens", 0) or 0,
            getattr(response.usage, "cost", None),
            _thinking_tok,
            _cached_tok,
        )

    def _handle_write_handoff(
        self,
        tc: ChatCompletionMessageFunctionToolCall,
        result: str,
        description: str,
        tool_records: list[ToolCallRecord],
        message_response: tuple,
    ) -> str:
        """Terminate the subagent's turn immediately on WRITE_HANDOFF_SENTINEL.

        Mirrors the tool-message bookkeeping the normal dispatch path performs
        (via `_bookkeep_tool_call`/`_finalize_turn`), then short-circuits the
        run() call — no further tool calls or API turns happen after this.
        """
        message, response = message_response
        clean = result.replace(WRITE_HANDOFF_SENTINEL, "").strip()

        full_str = self._bookkeep_tool_call(tc, clean, description, tool_records)
        self._finalize_turn(message, response, tool_records)

        self.callbacks.on_done(full_str)
        return full_str

    # ── Plan mode transitions ─────────────────────────────────────────────────

    def _handle_enter_plan_mode(self, args: dict) -> str:
        mode = args.get("mode", "interactive")
        task_summary = (args.get("task_summary") or "").strip()
        if not task_summary:
            return "Error: task_summary is required when entering plan mode."

        interactive = mode != "autonomous"
        dagi_root = DAGI_ROOT
        plans_dir = self.config.project_path / ".dagi" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_dir = plans_dir / f"plan_{ts}"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text(
            f"# Plan: {task_summary}\n\n"
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
            "#### Tests\n\n"
            "## Notes\n\n"
            "## Verification\n\n",
            encoding="utf-8",
        )

        self.config.previous_branch = get_current_branch(self.config.project_path)

        branch_name: str | None = None
        branch_creation_failed = False
        try:
            branch_name = create_task_branch(self.config.project_path, task_summary, plan_dir.name)
        except RuntimeError as e:
            branch_creation_failed = True
            self.callbacks.on_assistant_text(f"[git] Could not create task branch: {e}")

        if branch_name:
            branch_note = f"**Branch:** `{branch_name}`"
        elif branch_creation_failed:
            branch_note = (
                "**Branch:** (branch creation failed — see notice above — "
                "continuing without a git workflow)"
            )
        else:
            branch_note = "**Branch:** (no git repository detected — skipping git workflow)"

        self._handle_switch_model("plan", {"reason": "entering plan mode"})
        to_name = self.config.display_name or self.config.model

        self.callbacks.on_assistant_text(
            f"Entering plan mode — switching to advanced model ({to_name}).\n\n"
            f"**Plan file:** `{plan_file}`\n\n**Mode:** {mode}\n\n{branch_note}"
        )

        self._rebuild_for_plan_mode(dagi_root, plan_file, interactive=interactive)

        return (
            f"Plan mode activated ({mode} mode). Advanced model: {to_name}.\n\n"
            f"Plan file: {plan_file}\n\n"
            f"{branch_note}\n\n"
            f"Tools restricted to: read, grep, find, write/edit (plan file only), "
            f"web_research, skill, run_skill_script, ask_user, show_plan, exit_plan_mode."
        )

    def _handle_exit_plan_mode(self, args: dict) -> str:
        saved_plan = self.config.plan_file
        dagi_root = DAGI_ROOT
        self._handle_switch_model("default", {"reason": "plan complete, returning to normal mode"})
        self.config.active_plan_file = saved_plan
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

    def _handle_all_tasks_resolved(self) -> str:
        cleared = self.config.active_plan_file
        self.config.active_plan_file = None
        self._rebuild_for_normal_mode(DAGI_ROOT)
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
                    "Cannot switch to 'advanced' tier: no advanced_model is configured in .dagi/config.yaml. "
                    "Continuing with the current model."
                )
        elif target == "worker":
            tier_cfg = self.config.worker_config
            if tier_cfg is None:
                return (
                    "Cannot switch to 'worker' tier: no worker_model is configured in .dagi/config.yaml. "
                    "Continuing with the current model."
                )
        elif target == "default":
            snap = self._base_config_snapshot
            self.config.model          = snap["model"]
            self.config.base_url       = snap["base_url"]
            self.config.api_key        = snap["api_key"]
            self.config.thinking       = snap["thinking"]
            self.config.display_name   = snap["display_name"]
            self.config.provider_order = snap["provider_order"]
            tier_cfg = None
        else:
            return f"Unknown model tier '{target}'. Valid values: plan, default, worker."

        if tier_cfg is not None:
            self.config.model          = tier_cfg.model
            self.config.base_url       = tier_cfg.base_url
            self.config.api_key        = tier_cfg.api_key
            self.config.thinking       = tier_cfg.thinking
            self.config.display_name   = tier_cfg.display_name
            self.config.provider_order = tier_cfg.provider_order

        self.client = openai.OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)

        self._extra_body = {}
        if self.config.thinking and self.config.thinking.lower() != "none":
            self._extra_body["reasoning"] = {"effort": self.config.thinking.lower()}
        if self.config.cache_prompt:
            self._extra_body["cache_prompt"] = True
        if self.config.provider_order:
            self._extra_body["provider"] = {"order": self.config.provider_order}

        self._current_tier = target
        to_name = self.config.display_name or self.config.model
        self.callbacks.on_model_switch(from_name, to_name)

        return f"Switched to '{target}' tier: {to_name}. Reason: {reason}"

    def _build_preamble(self, dagi_root: Path) -> str:
        parts: list[str] = []
        if self.config.system_prompt_preamble:
            parts.append(self.config.system_prompt_preamble.strip())
        soul_text = load_soul(dagi_root, self.config.project_path)
        if soul_text:
            parts.append(soul_text.strip())
        for agents_path in [
            dagi_root / "AGENTS.md",
            self.config.project_path / "AGENTS.md",
        ]:
            if agents_path.exists():
                text = agents_path.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(text)
        return "\n\n---\n\n".join(parts)

    def _assemble_system_string(self, dagi_root: Path) -> str:
        """Single source of truth for system-prompt assembly.

        Reads self.config and self.registry; also refreshes self.system_parts for
        the UI expander. Call sites handle _messages assignment via _sync_messages().
        """
        readme_path = (dagi_root / "README.md").resolve()
        prompt_text = (
            self.config.system_prompt
            if self.config.system_prompt
            else load_main_system_prompt(dagi_root, self.config.project_path)
        )
        tools_and_skills = _format_tools_and_skills(self.registry, self.skills)
        prompt = prompt_text.format_map(_SafeDict(
            readme_path=readme_path,
            tools_and_skills=tools_and_skills,
            cwd=str(self.config.project_path.resolve()),
            memory_root=str(self._effective_memory_root),
            dagi_root=str(dagi_root.resolve()),
        ))

        soul_text = load_soul(dagi_root, self.config.project_path)
        dagi_agents = dagi_root / "AGENTS.md"
        project_agents = self.config.project_path / "AGENTS.md"
        self.system_parts = []
        if soul_text:
            self.system_parts.append({"label": "SOUL.md", "content": soul_text.strip()})
        if dagi_agents.exists():
            self.system_parts.append({
                "label": "AGENTS.md (dagi)",
                "content": dagi_agents.read_text(encoding="utf-8").strip(),
            })
        if project_agents.exists():
            self.system_parts.append({
                "label": "AGENTS.md (project)",
                "content": project_agents.read_text(encoding="utf-8").strip(),
            })
        self.system_parts.append({"label": "System Prompt", "content": prompt})

        preamble = self._build_preamble(dagi_root)
        sections = [s for s in [preamble, prompt] if s]
        system = "\n\n---\n\n".join(sections)
        system += f"\n\n---\n\nProject root: {self.config.project_path}"

        self._system_prefix = system
        return system

    _DYNAMIC_CONTEXT_SENTINEL = "## Session Context"

    def _build_dynamic_context(self) -> str:
        """Build the dynamic context board appended as the last message.

        Contains mutable session state that the model should always see:
        python env, active plan status. Kept lean — titles and markers
        only. The model reads the plan file for full task descriptions.
        """
        from tools._plan_parser import parse_subtask_statuses

        parts = [self._DYNAMIC_CONTEXT_SENTINEL]

        if self.config.python_env:
            parts.append(f"Python env: {self.config.python_env}")

        plan_file = self.config.active_plan_file
        if plan_file and not self.config.plan_mode:
            parts.append(f"Plan: {plan_file}")
            try:
                text = Path(plan_file).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                text = ""

            statuses = parse_subtask_statuses(text)
            if statuses:
                # Active = first in_progress, else first pending
                active = next(
                    (s for s in statuses if s["status"] == "in_progress"),
                    next(
                        (s for s in statuses if s["status"] == "pending"),
                        None,
                    ),
                )
                if active:
                    idx = statuses.index(active) + 1
                    parts.append(f"Active: {idx}. {active['name']}")

                marker_map = {
                    "pending": " ", "in_progress": "~",
                    "complete": "x", "failed": "!",
                }
                status_line = " ".join(
                    f"{i}.[{marker_map.get(s['status'], '?')}]"
                    for i, s in enumerate(statuses, start=1)
                )
                parts.append(f"Status: {status_line}")

        return "\n".join(parts)

    def _refresh_dynamic_context(self) -> None:
        """Re-render the board and log it if it changed.

        The board is *ephemeral*: it is never a member of ``_messages`` and
        never a surface node. ``_build_request_messages`` appends it as the
        final message of each request, so the reusable prefix through the
        last real message stays byte-identical from step to step.
        """
        board = self._build_dynamic_context()
        if board == self._board:
            return
        self._board = board
        self.log.append(sev.PLAN_WRITE, {"board": board})

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
            memory_root=self._effective_memory_root,
            bash_tool=self._injected_bash_tool,
            session_log=self.log,
        )

        _system = self._assemble_system_string(dagi_root)
        self._emit_header(_system, "change")
        self._sync_messages()

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
            session_log=self.log,
        )
        _system = self._assemble_system_string(dagi_root)
        self._emit_header(_system, "change")
        self._sync_messages()

    def _rebuild_for_reload(self) -> tuple[set[str], set[str], list[tuple[str, str]]]:
        """Hot-reload skills from disk, rebuild registry + system prompt preserving current mode.

        Returns (added_names, removed_names, errors) for notification formatting.
        """
        dagi_root = DAGI_ROOT
        skill_roots = [
            dagi_root / ".dagi" / "skills",
            self.config.project_path / ".dagi" / "skills",
        ]

        before_names = {s.name for s in self.skills}
        new_skills, errors = SkillLoader().load_all_with_errors(skill_roots, dagi_root=dagi_root)
        self.skills = new_skills
        after_names = {s.name for s in self.skills}

        if self.config.plan_mode and self.config.plan_file:
            interactive = self.config.plan_mode_initiated_by == "user"
            self._rebuild_for_plan_mode(dagi_root, Path(self.config.plan_file), interactive=interactive)
        else:
            self._rebuild_for_normal_mode(dagi_root)

        return after_names - before_names, before_names - after_names, errors

    def finish(self) -> None:
        """Finalize the session — write session_end to JSONL. Called by the CLI at session end."""
        self.tracker.finish(raw_messages=self._messages)
