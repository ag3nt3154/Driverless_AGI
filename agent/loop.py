from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
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
from agent.affect import AffectRestore, AffectSnapshot
from agent.dynamic_context import SENTINEL as DYNAMIC_CONTEXT_SENTINEL
from agent.lifecycle import LifecyclePublisher, build_dynamic_context_with_affect
from agent.lifecycle import ensure_affect_controller, load_process_library
from agent.process_state import ProcessSnapshot, ProcessStateController
from agent.prompts import load_prompt, load_main_system_prompt, load_soul
from agent.registry import ToolRegistry
from agent import session_events as sev
from agent.parent_context import ForkMode, ParentContextProvider, ParentFork
from agent.session import SessionTracker, ToolCallRecord
from agent.session_log import InvariantError, SessionLog, is_status_board
from agent.session_store import append_event
from agent.skills import Skill, SkillLoader
from tools.subagent_api import build_fork_context, run_subagent
from tools.compact._tail_boundary import compute_tail_boundary
from tools.update_task_status import UPDATE_TASK_STATUS_SENTINEL
from tools.plan_mode import ENTER_PLAN_MODE_SENTINEL, EXIT_PLAN_MODE_SENTINEL
from tools.reload_skills import RELOAD_SKILLS_SENTINEL
from tools.output_filter import filter_tool_output
from tools.switch_model import parse_switch_sentinel

# Loop sentinels, helpers, and CONTINUE_PROMPT moved verbatim to
# agent/_loop_helpers.py; re-exported here for backward compatibility.
from agent._loop_helpers import (  # noqa: F401
    AWAIT_USER_FLAG,
    CONTINUE_PROMPT,
    TASK_END_FLAG,
    WRITE_HANDOFF_SENTINEL,
    _LOOP_SENTINELS,
    _build_wiki_index_context,
    _escape_sentinels,
    _extract_reasoning,
    _format_reload_notification,
)


# Plan-mode lifecycle moved verbatim to agent/_plan_mode.py;
# _is_plan_empty re-exported here for backward compatibility.
from agent._plan_mode import _is_plan_empty  # noqa: F401,E402

# Compaction/config/callback dataclasses moved verbatim to agent/_loop_config.py;
# re-exported here for backward compatibility with existing importers.
from agent._loop_config import (  # noqa: F401
    _NO_COMPACTION,
    AgentCallbacks,
    AgentConfig,
    CompactionResult,
)


class AgentLoop:
    def __init__(
        self,
        config: AgentConfig,
        callbacks: AgentCallbacks | None = None,
        initial_messages: list | None = None,
        initial_affect: AffectRestore | None = None,
        _registry: "ToolRegistry | None" = None,
        _parent_tracker: "SessionTracker | None" = None,
        _subagent_id: str | None = None,
        _tracker: "SessionTracker | None" = None,
        _bash_tool: "object | None" = None,
        _system_prompt_override: str | None = None,
        _preserve_request_prefix: bool = False,
    ):
        from agent.tools import create_tool_registry
        from uuid import uuid4

        self.callbacks = callbacks or AgentCallbacks()
        dagi_root = DAGI_ROOT
        self._system_prompt_override = _system_prompt_override
        self._preserve_request_prefix = _preserve_request_prefix

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
        _tracker_path = getattr(self.tracker, "_path", None)
        if isinstance(_tracker_path, Path):
            _events_path = _tracker_path.with_suffix(".events.jsonl")
            self.log.on_append = lambda event: append_event(_events_path, event)

        if _registry is not None:
            # Sub-agent path: use the provided registry, skip skill loading
            self.registry = _registry
            self.skills = []
            if self.tracker.affect_controller is not None:
                self.tracker.affect_controller.set_listener(self.callbacks.on_affect_changed)
        else:
            ensure_affect_controller(
                self.tracker, config, dagi_root, self.callbacks, initial_affect
            )
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
                parent_context=self.parent_context_provider,
                affect_controller=self.tracker.affect_controller,
            )

        self.config = config
        self._process = ProcessStateController(
            load_process_library(dagi_root),
            on_change=self.callbacks.on_process_state_changed,
        )
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
        # Single source of truth shared with agent/_model_switch.handle_switch_model.
        self._parallel_tool_calls = False
        from agent._model_switch import build_extra_body

        self._extra_body: dict = build_extra_body(
            config.thinking, config.cache_prompt, config.provider_order,
        )

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
        #: Snapshot of the last provider request's identity fields.
        #: Captured at the API call site, before the provider returns.
        #: Used by compact() to build the fork-context file.
        self._last_request_snapshot: dict | None = None

        # Switch to plan tier immediately when starting in user-initiated plan mode
        if config.plan_mode and config.advanced_config is not None:
            self._handle_switch_model("plan", {"reason": "user-initiated plan mode"})

        self._lifecycle = LifecyclePublisher(self._process)
        self._pause_event = self._lifecycle.pause_event
        self._pause_checkpoint = threading.Event()

    def pause(self) -> None:
        self._lifecycle.pause()

    def inject_and_resume(self, message: str) -> None:
        self._log_user_message("user", message, "inject")
        self._lifecycle.resume_thinking()

    @property
    def parent_context_provider(self) -> ParentContextProvider:
        """Expose loop-owned capture hooks to inherited-subagent callers."""
        return ParentContextProvider(
            capture_fork=self.capture_parent_fork,
            get_surface_generation=lambda: self.log.surface.generation,
        )

    def wait_for_pause_checkpoint(self, timeout: float) -> bool:
        """Wait until a paused run reaches its safe pre-request checkpoint."""
        return self._pause_checkpoint.wait(timeout)

    def _continuing_step_finished(self, turn: int, step: int) -> None:
        self.log.append(sev.STEP_END, {"turn": turn, "step": step})

    def _freeze_request_snapshot(self, create_kwargs: Mapping[str, Any]) -> dict[str, Any]:
        """Copy request identity and the live surface boundary before a provider call."""
        nodes = self.log.surface.nodes
        return {
            "model": create_kwargs["model"],
            "messages": copy.deepcopy(create_kwargs["messages"]),
            "tools": copy.deepcopy(create_kwargs.get("tools", [])),
            "parallel_tool_calls": create_kwargs.get("parallel_tool_calls", False),
            "extra_body": copy.deepcopy(create_kwargs.get("extra_body", {})),
            "base_url": self.config.base_url or "",
            "parent_cut_seq": nodes[-1] if nodes else 0,
            "parent_surface_generation": self.log.surface.generation,
        }

    def _fork_coordinates(self) -> tuple[int, int]:
        """Return the live step, or the most recently completed step when idle."""
        if self.log.open_turn is not None:
            return self.log.open_turn, self.log.open_step or 0
        for event in reversed(self.log.events):
            turn = event.data.get("turn")
            step = event.data.get("step")
            if isinstance(turn, int) and isinstance(step, int):
                return turn, step
        return 0, 0

    def capture_parent_fork(self, branch_id: str, mode: ForkMode) -> ParentFork:
        """Freeze a spawn or stable prefix and record its non-surface branch point."""
        if mode == "spawn":
            if self._last_request_snapshot is None:
                raise RuntimeError("Cannot capture a spawn fork before a provider request")
            snapshot = copy.deepcopy(self._last_request_snapshot)
        elif mode == "stable":
            if self.log.open_turn is not None and not self._pause_checkpoint.is_set():
                raise RuntimeError("Open loop has not reached a safe checkpoint")
            create_kwargs = {
                "model": self.config.model,
                "messages": self._build_request_messages(),
                "tools": self.registry.get_openai_tools_list(),
                "parallel_tool_calls": False,
            }
            if self._extra_body:
                create_kwargs["extra_body"] = self._extra_body
            snapshot = self._freeze_request_snapshot(create_kwargs)
        else:
            raise ValueError(f"Unknown fork mode: {mode!r}")

        request = {
            key: copy.deepcopy(snapshot[key])
            for key in (
                "model", "messages", "tools", "parallel_tool_calls", "extra_body", "base_url"
            )
        }
        cut_seq = snapshot["parent_cut_seq"]
        generation = snapshot["parent_surface_generation"]
        turn, step = self._fork_coordinates()
        self.log.append(
            sev.BRANCH_START,
            {
                "branch": branch_id,
                "parent_branch": "main",
                "turn": turn,
                "step": step,
                "parent_cut_seq": cut_seq,
                "parent_surface_generation": generation,
            },
        )
        return ParentFork(branch_id, cut_seq, generation, request)

    def _compact_context(self) -> CompactionResult:
        """Delegates to self.compact (body moved verbatim to
        agent/_compaction.compact). Failures are non-fatal — the session
        continues with un-compacted messages rather than crashing."""
        try:
            return self.compact()
        except Exception as exc:
            self.callbacks.on_assistant_text(
                f"[Warning: context compaction failed — {exc}. Continuing with full context.]"
            )
            return _NO_COMPACTION

    def run_wtf(self, description: str | None) -> "WtfResult":
        """Delegate inherited diagnostic orchestration to its focused module."""
        from agent.wtf import run_wtf

        return run_wtf(self, description)

    def _consume_stream(self, stream) -> "tuple[SimpleNamespace, object | None]":
        """Delegate to agent/_streaming.consume_stream (moved verbatim)."""
        from agent._streaming import consume_stream

        return consume_stream(stream, self.callbacks)

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
        from agent._compaction import collect_steps

        return collect_steps(self.log)

    def _find_surface_index_for_step(self, target: tuple[int, int]) -> int:
        from agent._compaction import find_surface_index_for_step

        return find_surface_index_for_step(self.log, target)

    def _log_compaction(self, result: CompactionResult, tail_first_step: tuple[int, int]) -> None:
        from agent._compaction import log_compaction

        log_compaction(self.log, result, tail_first_step, self._sync_messages)

    def compact(self, force: bool = False) -> CompactionResult:
        """Delegate to agent/_compaction.compact (moved verbatim)."""
        from agent._compaction import compact as _compact

        return _compact(self, force)

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
            self._process.idle()
            self.callbacks.on_assistant_text(notification)
            return notification

        _turn = self.log.next_turn()
        self.log.append(sev.TURN_START, {"turn": _turn})

        if not self._preserve_request_prefix:
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
                if not self._preserve_request_prefix:
                    self._refresh_dynamic_context()
                self.callbacks.on_iteration(iteration)
                self._pause_checkpoint.set()
                try:
                    self._pause_event.wait()  # blocks here when paused; instant no-op otherwise
                finally:
                    self._pause_checkpoint.clear()

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
                    self._lifecycle.api_attempt_started()
                    _request = self._build_request_messages()
                    self.callbacks.on_api_call(list(_request))
                    try:
                        _create_kwargs = dict(
                            model=self.config.model,
                            messages=_request,
                            tools=self.registry.get_openai_tools_list(),
                            parallel_tool_calls=self._parallel_tool_calls,
                            **(dict(extra_body=self._extra_body) if self._extra_body else {}),
                        )
                        self._last_request_snapshot = self._freeze_request_snapshot(_create_kwargs)
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
                                self.pause()
                                self.callbacks.on_pause()
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
                                self.pause()
                                self.callbacks.on_pause()
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
                        self._process.error()
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
                    self.tracker.record_assistant(
                        message.content, response.usage, tool_records,
                        cached_tokens=_cached_tok, thinking_tokens=_thinking_tok,
                    )

                    # Check for either exit flag (TASK_END_FLAG kept as legacy alias)
                    _exit_flag = (
                        AWAIT_USER_FLAG if AWAIT_USER_FLAG in result else
                        TASK_END_FLAG   if TASK_END_FLAG   in result else
                        None
                    )
                    if _exit_flag:
                        clean = result.replace(_exit_flag, "").strip()
                        self.callbacks.on_assistant_text(clean)
                        self._process.idle()
                        self.callbacks.on_done(clean)
                        self._close_turn(_turn, sev.reason_completed())
                        return clean

                    # Task not complete — inject "continue" and keep looping
                    self.callbacks.on_assistant_text(result)
                    if self._continuation_count >= self.config.max_continuations:
                        self._process.idle()
                        self.callbacks.on_done(result)
                        self._close_turn(_turn, sev.reason_max_continuations())
                        return result
                    self._continuation_count += 1
                    self._log_user_message("user", CONTINUE_PROMPT, "continue")
                    self.callbacks.on_continue_injected(
                        self._continuation_count, self.config.max_continuations
                    )
                    self._continuing_step_finished(_turn, iteration)
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

                self._continuing_step_finished(_turn, iteration)

        except Exception as e:
            self._close_turn(_turn, sev.reason_error(str(e), type(e).__name__))
            self._process.error()
            self.callbacks.on_error(e)
            raise
        finally:
            # Defensive: any exit path added later without an explicit close
            # still leaves the log well-formed rather than half-open.
            self._close_turn(_turn, sev.reason_error("turn closed without a reason"))

    def _dispatch_tool_calls(self, message, response, tool_records) -> str | None:
        """Delegate to agent/_tool_dispatch.dispatch_tool_calls (moved verbatim)."""
        from agent._tool_dispatch import dispatch_tool_calls

        return dispatch_tool_calls(self, message, response, tool_records)

    def _bookkeep_tool_call(
        self,
        tc: ChatCompletionMessageFunctionToolCall,
        result,
        description: str,
        tool_records: list[ToolCallRecord],
    ) -> str:
        from agent._tool_dispatch import bookkeep_tool_call

        return bookkeep_tool_call(self, tc, result, description, tool_records)

    def _finalize_turn(self, message, response, tool_records: list[ToolCallRecord]) -> None:
        from agent._tool_dispatch import finalize_turn

        return finalize_turn(self, message, response, tool_records)

    def _handle_write_handoff(
        self,
        tc: ChatCompletionMessageFunctionToolCall,
        result: str,
        description: str,
        tool_records: list[ToolCallRecord],
        message_response: tuple,
    ) -> str:
        from agent._tool_dispatch import handle_write_handoff

        return handle_write_handoff(self, tc, result, description, tool_records, message_response)

    # ── Plan mode transitions ─────────────────────────────────────────────────

    def _handle_enter_plan_mode(self, args: dict) -> str:
        from agent._plan_mode import handle_enter_plan_mode

        return handle_enter_plan_mode(self, args)

    def _handle_exit_plan_mode(self, args: dict) -> str:
        from agent._plan_mode import handle_exit_plan_mode

        return handle_exit_plan_mode(self, args)

    def _handle_all_tasks_resolved(self) -> str:
        from agent._plan_mode import handle_all_tasks_resolved

        return handle_all_tasks_resolved(self)

    def _handle_switch_model(self, target: str, args: dict) -> str:
        from agent._model_switch import handle_switch_model

        return handle_switch_model(self, target, args)

    def _assemble_system_string(self, dagi_root: Path) -> str:
        """Single source of truth for system-prompt assembly.

        Body moved verbatim to agent/_system_prompt.assemble_system_string;
        instance state (system_parts / _system_prefix) is assigned here.
        Call sites handle _messages assignment via _sync_messages().
        """
        from agent._system_prompt import assemble_system_string

        system, self.system_parts = assemble_system_string(
            config=self.config,
            registry=self.registry,
            skills=self.skills,
            effective_memory_root=self._effective_memory_root,
            system_prompt_override=self._system_prompt_override,
            dagi_root=dagi_root,
        )
        self._system_prefix = system
        return system

    _DYNAMIC_CONTEXT_SENTINEL = DYNAMIC_CONTEXT_SENTINEL

    def _build_dynamic_context(self) -> str:
        return build_dynamic_context_with_affect(self.config, self.tracker.affect_controller)

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
        from agent._plan_mode import rebuild_for_normal_mode

        rebuild_for_normal_mode(self, dagi_root)

    def _rebuild_for_plan_mode(self, dagi_root: Path, plan_file: Path, interactive: bool = True) -> None:
        from agent._plan_mode import rebuild_for_plan_mode

        rebuild_for_plan_mode(self, dagi_root, plan_file, interactive)

    def _rebuild_for_reload(self) -> tuple[set[str], set[str], list[tuple[str, str]]]:
        """Hot-reload skills; body moved to agent/_plan_mode.rebuild_for_reload."""
        from agent._plan_mode import rebuild_for_reload

        return rebuild_for_reload(self)

    def finish(self) -> None:
        """Finalize the session — write session_end to JSONL. Called by the CLI at session end."""
        self.tracker.finish(raw_messages=self._messages)
