from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
)

from agent import DAGI_ROOT
from agent._git_branch import create_task_branch, get_current_branch
from agent._request_executor import RequestExecutor, RequestOutcome
from agent._turns import TurnBoundaries
from agent.lifecycle import LifecyclePublisher
from agent.lifecycle import ensure_expression_controller, load_process_library
from agent.process_state import ProcessSnapshot, ProcessStateController
from agent.prompts import load_prompt, load_main_system_prompt, load_soul
from agent.registry import ToolRegistry
from agent import session_events as sev
from agent.parent_context import ForkMode, ParentContextProvider, ParentFork
from agent.session import SessionTracker, ToolCallRecord
from agent.session_log import InvariantError, SessionLog
from agent.session_store import append_event
from agent.skills import Skill, SkillLoader
from agent.user_input import UserSubmission
from agent.image_assets import ImageAssetStore, materialize_messages
from tools.subagent_api import build_fork_context, run_subagent
from tools.compact._tail_boundary import compute_tail_boundary, estimate_tokens
from tools.output_filter import filter_tool_output

from agent._loop_helpers import (  # noqa: F401
    CONTINUE_PROMPT,
    _build_memory_context,
    _extract_reasoning,
    _format_reload_notification,
)

_EMPTY_CONTENT_THRESHOLD = 3



# Compaction/config/callback dataclasses moved verbatim to agent/_loop_config.py;
# re-exported here for backward compatibility with existing importers.
from agent._loop_config import (  # noqa: F401
    _NO_COMPACTION,
    AgentCallbacks,
    AgentConfig,
    CompactionResult,
    resolve_memory_root,
)


class AgentLoop:
    def __init__(
        self,
        config: AgentConfig,
        callbacks: AgentCallbacks | None = None,
        initial_messages: list | None = None,
        initial_affect=None,
        _registry: "ToolRegistry | None" = None,
        _parent_tracker: "SessionTracker | None" = None,
        _subagent_id: str | None = None,
        _bash_tool: "object | None" = None,
        _system_prompt_override: str | None = None,
        _preserve_request_prefix: bool = False,
        tracker: "SessionTracker | None" = None,
        session_log: "SessionLog | None" = None,
    ):
        # Phases run in a fixed order: each may read state an earlier one set
        # (e.g. subagent tools receive the event log; the system prompt reads
        # the registry and config). Pinned by tests/test_loop_construction.py.
        self.callbacks = callbacks or AgentCallbacks()
        self._system_prompt_override = _system_prompt_override
        self._preserve_request_prefix = _preserve_request_prefix

        # Stash injected bash tool so plan-mode rebuilds can restore it
        self._injected_bash_tool = _bash_tool

        # ── Create tracker first so sub-agent tools can reference it ─────────
        self.tracker = self._init_tracker(config, tracker, _parent_tracker, _subagent_id)
        self._effective_memory_root = resolve_memory_root(config.memory_root)
        self._init_event_log(session_log)
        self._init_tools(config, _registry, initial_affect, _bash_tool)
        self.config = config
        system = self._init_conversation(initial_messages, session_log)
        self._init_model_client(config)
        self.tracker.record_system(system)
        self._init_run_state()

    def _init_tracker(
        self,
        config: AgentConfig,
        tracker: "SessionTracker | None",
        parent_tracker: "SessionTracker | None",
        subagent_id: str | None,
    ) -> SessionTracker:
        """Use the caller's tracker, else a child of the parent's, else a fresh one."""
        from uuid import uuid4

        if tracker is not None:
            return tracker
        if parent_tracker is not None:
            return parent_tracker.child_tracker(subagent_id or uuid4().hex)
        return SessionTracker(
            model=config.model,
            thread_id=config.thread_id,
            logs_dir=config.project_path / ".dagi" / "logs",
        )

    def _init_event_log(self, session_log: "SessionLog | None") -> None:
        """Adopt or create the session log and bind its events file."""
        if session_log is not None:
            self.log = session_log
        else:
            self.log = SessionLog()
        self.turns = TurnBoundaries(self.log)
        # Fixed here: the tracker may rename its own file later (slug), but
        # appends and whole-log rewrites must keep targeting the same file.
        self._events_path: Path | None = None
        _tracker_path = getattr(self.tracker, "_path", None)
        if isinstance(_tracker_path, Path):
            _events_path = self._events_path = _tracker_path.with_suffix(".events.jsonl")
            self.log.on_append = lambda event: append_event(_events_path, event)

    def _init_tools(
        self,
        config: AgentConfig,
        registry: "ToolRegistry | None",
        initial_affect,
        bash_tool: "object | None",
    ) -> None:
        """Adopt a subagent's registry, or load skills and build the main registry."""
        from agent.tools import create_tool_registry

        dagi_root = DAGI_ROOT
        if registry is not None:
            # Sub-agent path: use the provided registry, skip skill loading
            self.registry = registry
            self.skills = []
            controller = self.tracker.expression_controller
            if controller is not None:
                controller.set_listener(self.callbacks.on_expression_changed)
            return
        ensure_expression_controller(
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
            config=config,
            callbacks=self.callbacks,
            tracker=self.tracker,
            memory_root=self._effective_memory_root,
            bash_tool=bash_tool,
            session_log=self.log,
            parent_context=self.parent_context_provider,
            expression_controller=self.tracker.expression_controller,
        )

    def _init_conversation(
        self, initial_messages: list | None, session_log: "SessionLog | None",
    ) -> str:
        """Build the system prompt and header, seed the message cache; return the prompt."""
        dagi_root = DAGI_ROOT
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
        # (self.log is initialized earlier, before create_tool_registry, so it
        # can be forwarded to subagent tools at construction time.)
        self._emit_header(system, "resume" if initial_messages else "initial")
        # A supplied log already owns the conversation. Replaying its derived
        # messages would duplicate the entire history on every GUI prompt.
        if initial_messages and session_log is None:
            self._seed_from_messages(initial_messages)
        self._sync_messages()
        return system

    def _init_model_client(self, config: AgentConfig) -> None:
        """Build the provider client and snapshot the default model tier."""
        from agent._model_switch import build_openai_client, build_extra_body

        self.client, script_rk = build_openai_client(config)
        if script_rk:
            config.request_kwargs = script_rk
        self._parallel_tool_calls = config.parallel_tool_calls

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
            "client_script":  config.client_script,
            "request_kwargs": dict(config.request_kwargs),
            "parallel_tool_calls": config.parallel_tool_calls,
        }
        self._current_tier: str = "default"

    def _init_run_state(self) -> None:
        """Per-run counters, pause/abort signalling and mid-step injection state."""
        # Reset at the start of each run() call — counts "continue" injections for that task only
        self._continuation_count: int = 0
        self._empty_content_streak: int = 0
        self._last_prompt_tokens: int = 0
        self._compaction_generation: int = 0
        #: Snapshot of the last provider request's identity fields.
        #: Captured at the API call site, before the provider returns.
        #: Used by compact() to build the fork-context file.
        self._last_request_snapshot: dict | None = None

        self._lifecycle = LifecyclePublisher(self._process)
        self._pause_event = self._lifecycle.pause_event
        self._pause_checkpoint = threading.Event()
        # Esc / stop button: interrupt() sets this to abandon the request in
        # flight. It is separate from the pause flag because a resume may
        # arrive before the loop has noticed, and the late response must still
        # be dropped, not acted on.
        self._abort_request = threading.Event()
        self._active_stream = None
        # Messages injected while the loop thread is mid-step are logged by
        # that thread at its next checkpoint, so they never land between a
        # tool call and its result.
        self._inject_lock = threading.RLock()
        self._injected: list[UserSubmission] = []
        self._mid_step = False
        self._in_run = False
        self._expression_timer: threading.Timer | None = None
        self._expression_controller = self.tracker.expression_controller

    # ── Public state for frontends ───────────────────────────────────────────

    @property
    def messages(self) -> list[dict]:
        """A copy of the conversation as last sent to the model (header first)."""
        return list(self._messages)

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    @property
    def is_running(self) -> bool:
        """True while ``run()`` is executing a turn."""
        return self._in_run

    def revise_last_steps(self, n: int, *, keep_turn: bool = False) -> int:
        """Remove up to ``n`` steps from the log and refresh ``messages``.

        Stops early when no completed step is left; returns how many were
        removed. ``keep_turn`` keeps a turn (and its user message) whose last
        step is removed. The revision always applies in memory; the rewritten
        log is then saved, and a failure to save is raised to the caller.
        """
        from agent.session_store import write_session

        removed = 0
        while removed < n and self.log.peek_last_step() is not None:
            self.log.revise_last_step(keep_turn=keep_turn)
            removed += 1
        self._sync_messages()
        if removed and self._events_path is not None:
            write_session(self._events_path, self.log.events)
        return removed

    def pause(self) -> None:
        self._lifecycle.pause()

    def interrupt(self) -> bool:
        """Stop now: pause, kill bash, code scripts and subagents, abandon the request.

        A streamed request is closed at once; a blocking one is left to finish
        and its response is discarded. Returns False when already paused.
        """
        if not self._pause_event.is_set():
            return False
        self._abort_request.set()
        self.pause()
        bash = self.registry._tools.get("bash")
        if bash is not None:
            bash.force_kill()
        code = self.registry._tools.get("code")
        if code is not None:
            code.force_kill()
        from tools._subagent_runner import force_kill_active_subagents
        force_kill_active_subagents()
        self._close_active_stream()
        return True

    def _close_active_stream(self) -> None:
        stream = self._active_stream
        if stream is not None:
            try:
                stream.close()
            except Exception:  # noqa: BLE001 - best effort; the chunk check still stops it
                pass

    def inject_and_resume(self, message: str | UserSubmission) -> None:
        submission = message if isinstance(message, UserSubmission) else UserSubmission(text=message)
        with self._inject_lock:
            if self._mid_step:
                self._injected.append(submission)
            else:
                self._log_injected(submission)
        self._lifecycle.resume_thinking()

    def steer(self, message: str | UserSubmission) -> bool:
        """Add a message to the running turn without pausing it.

        It is logged at the loop's next checkpoint (after the current tool
        calls, before the next model call). Returns False when no turn is
        running; the caller should send it as a new turn instead. A message
        still queued when the turn ends is dropped here — the caller keeps
        its own copy and resends anything ``on_user_injected`` never confirmed.
        """
        submission = message if isinstance(message, UserSubmission) else UserSubmission(text=message)
        with self._inject_lock:
            if not self._in_run:
                return False
            if self._mid_step:
                self._injected.append(submission)
            else:
                self._log_injected(submission)
        return True

    def cancel_steer(self, submission: UserSubmission) -> bool:
        """Withdraw a steered message that has not been logged yet."""
        with self._inject_lock:
            for i, queued in enumerate(self._injected):
                if queued is submission:
                    del self._injected[i]
                    return True
        return False

    def _log_injected(self, submission: UserSubmission) -> None:
        self._log_user_message("user", self._submission_content(submission), "inject")
        self.callbacks.on_user_injected(submission)

    def _set_mid_step(self, busy: bool) -> None:
        """Flip the mid-step flag; on reaching a checkpoint, log queued injections."""
        with self._inject_lock:
            self._mid_step = busy
            if not busy:
                queued, self._injected = self._injected, []
                for submission in queued:
                    self._log_injected(submission)

    def _submission_content(self, submission: UserSubmission) -> str | list[dict]:
        """Build the content payload for a UserSubmission.

        Text-only submissions collapse to a plain string (unchanged wire
        shape). Submissions carrying images are stored in the project's
        ImageAssetStore and represented as a content list: the text part
        (if any) first, then one ``dagi_image`` part per attachment.
        """
        if not submission.images:
            return submission.text
        store = ImageAssetStore(self.config.project_path)
        parts: list[dict] = []
        if submission.text.strip():
            parts.append({"type": "text", "text": submission.text})
        for attachment in submission.images:
            ref = store.store(attachment)
            parts.append(ref.to_content_part())
        return parts

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

    def _start_expression_timer(self) -> None:
        controller = self._expression_controller
        if controller is None:
            return
        interval = self.config.expression_interval
        if interval <= 0:
            return

        def tick() -> None:
            self._lifecycle.publish_expression_advance(controller)
            self._expression_timer = threading.Timer(interval, tick)
            self._expression_timer.daemon = True
            self._expression_timer.start()

        self._expression_timer = threading.Timer(interval, tick)
        self._expression_timer.daemon = True
        self._expression_timer.start()

    def _stop_expression_timer(self) -> None:
        if self._expression_timer is not None:
            self._expression_timer.cancel()
            self._expression_timer = None

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
                "parallel_tool_calls": self._parallel_tool_calls,
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
            self.callbacks.on_compaction_started()
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

    def _send_request(self):
        """One chat-completions attempt; RequestExecutor owns retries.

        Compacts first when the request would exceed the context budget.
        A streamed reply is accumulated into the blocking-response shape.
        """
        request = self._build_request_messages()
        if self.config.context_window > 0:
            est = sum(estimate_tokens(m) for m in request)
            budget = self.config.context_window - self.config.reserve_tokens
            if est > budget:
                self.callbacks.on_assistant_text(
                    f"[Context budget exceeded (~{est:,} tokens, "
                    f"budget {budget:,}). Compacting...]"
                )
                self._last_prompt_tokens = est
                self._compact_context()
                request = self._build_request_messages()

        self.callbacks.on_api_call(list(request))
        create_kwargs = dict(self.config.request_kwargs)
        create_kwargs.update(
            model=self.config.model,
            messages=request,
            tools=self.registry.get_openai_tools_list(),
            parallel_tool_calls=self._parallel_tool_calls,
        )
        if self._extra_body:
            create_kwargs.setdefault("extra_body", {})
            create_kwargs["extra_body"].update(self._extra_body)
        self._last_request_snapshot = self._freeze_request_snapshot(create_kwargs)
        if not self.config.stream:
            return self.client.chat.completions.create(**create_kwargs)

        stream = self.client.chat.completions.create(
            stream=True,
            stream_options={"include_usage": True},
            **create_kwargs,
        )
        self._active_stream = stream
        if self._abort_request.is_set():
            self._close_active_stream()
        try:
            msg, usage = self._consume_stream(stream)
        finally:
            self._active_stream = None
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)

    def _consume_stream(self, stream) -> "tuple[SimpleNamespace, object | None]":
        """Delegate to agent/_streaming.consume_stream (moved verbatim)."""
        from agent._streaming import consume_stream

        return consume_stream(stream, self.callbacks, self._abort_request)

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

    def _log_user_message(self, role: str, content, source: str) -> None:
        """Append one user/message surface event.

        `role` is durable. `source` is the semantic channel that tells
        wiki, reload, and human messages apart.

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

        Envelope header first, conversation next.
        Returns a fresh list: callers (including on_api_call observers) must
        not be able to mutate loop state through it.
        """
        messages = [self._header_message()]
        messages.extend(self._messages[1:])
        store = ImageAssetStore(self.config.project_path)
        return materialize_messages(messages, store)

    def _collect_steps(self) -> list[tuple[int, int]]:
        from agent._compaction import collect_steps

        return collect_steps(self.log)

    def _find_surface_index_for_step(self, target: tuple[int, int]) -> int:
        from agent._compaction import find_surface_index_for_step

        return find_surface_index_for_step(self.log, target)

    def _log_compaction(self, result: CompactionResult, tail_first_step: tuple[int, int]) -> None:
        from agent._compaction import log_compaction

        log_compaction(self.log, result, tail_first_step, self._sync_messages)

    def compact(self, force: bool = False, summarize_all: bool = False) -> CompactionResult:
        """Delegate to agent/_compaction.compact (moved verbatim)."""
        from agent._compaction import compact as _compact

        return _compact(self, force, summarize_all=summarize_all)

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

    def run(self, task: str | UserSubmission) -> str:
        submission = task if isinstance(task, UserSubmission) else UserSubmission(text=task)
        if submission.text.strip().lower() == "/reload":
            return self._run_reload()

        self.turns.open_turn()
        with self._inject_lock:
            self._in_run = True
        self._set_mid_step(True)

        try:
            self._log_task(submission)
            self._continuation_count = 0
            self._empty_content_streak = 0
            self._start_expression_timer()
            while True:
                step = self.turns.start_step()
                self.callbacks.on_iteration(step)
                self._wait_at_checkpoint()
                finished = self._run_step()
                if finished is not None:
                    result, reason = finished
                    self.turns.close_turn(reason)
                    return result
                self.turns.end_step()
        except Exception as e:
            self.turns.close_turn(sev.reason_error(str(e), type(e).__name__))
            self._process.error()
            self.callbacks.on_error(e)
            raise
        finally:
            with self._inject_lock:
                self._in_run = False
                self._mid_step = False
                self._injected.clear()
            self._stop_expression_timer()
            # Defensive: any exit path added later without an explicit close
            # still leaves the log well-formed rather than half-open.
            self.turns.close_turn(sev.reason_error("turn closed without a reason"))

    def _run_reload(self) -> str:
        added, removed, errors = self._rebuild_for_reload()
        notification = _format_reload_notification(len(self.skills), added, removed, errors)
        # A surface event needs an enclosing turn, and /reload short-circuits
        # before the normal one opens — so it gets its own.
        with self.turns.side_turn():
            self._log_user_message("user", notification, "reload")
        self._process.idle()
        self.callbacks.on_assistant_text(notification)
        return notification

    def _log_task(self, submission: UserSubmission) -> None:
        """Log the turn's opening user messages and name the session."""
        if not self._preserve_request_prefix:
            wiki_ctx = _build_memory_context(
                self._effective_memory_root, self.config.project_path
            )
            if wiki_ctx:
                self._log_user_message("user", wiki_ctx, "wiki")
        content = self._submission_content(submission)
        self._log_user_message("user", content, "human")
        self.tracker.record_user(content)

        # ── Auto-name session file from first user message ────────────────
        if not self._skip_slug_generation:
            slug_text = submission.text.strip()
            slug = self._generate_session_slug(slug_text) if slug_text else "image-conversation"
            if slug:
                self.tracker.rename_with_slug(slug)

    def _wait_at_checkpoint(self) -> None:
        """Between steps: block here while paused; consume any old interrupt."""
        self._set_mid_step(False)
        self._pause_checkpoint.set()
        try:
            self._pause_event.wait()  # instant no-op when not paused
        finally:
            self._pause_checkpoint.clear()
            self._set_mid_step(True)
        self._abort_request.clear()

    def _run_step(self) -> tuple[str, dict] | None:
        """One model request and its handling.

        Returns (result, turn-end reason) when the turn is over, or None to
        go on to the next step. Never closes the step or turn itself.
        """
        outcome = RequestExecutor(
            send=self._send_request,
            abort=self._abort_request,
            callbacks=self.callbacks,
            pause=self.pause,
            api_error_retries=self.config.api_error_retries,
            null_response_retries=self.config.null_response_retries,
            on_attempt=self._lifecycle.api_attempt_started,
        ).execute()
        response = outcome.response

        if outcome.outcome is RequestOutcome.PAUSED:
            return None  # next checkpoint blocks until the user resumes
        if outcome.outcome is RequestOutcome.ABORTED:
            self._keep_interrupted_text(response)
            return None  # next checkpoint waits for the user's next message
        if outcome.outcome is RequestOutcome.NULL_EXHAUSTED:
            error_msg = (
                f"Error: model returned a null response "
                f"{outcome.null_retries} time(s) in a row. "
                "Check your model endpoint and retry your task."
            )
            self._process.error()
            self.callbacks.on_error(Exception(error_msg))
            return error_msg, sev.reason_error(error_msg)

        message = response.choices[0].message
        reasoning = _extract_reasoning(message)
        if reasoning:
            self.callbacks.on_reasoning(reasoning)
        if message.tool_calls:
            return self._handle_tool_reply(message, response, reasoning)
        return self._handle_text_reply(message, response, reasoning)

    def _handle_text_reply(self, message, response, reasoning: str) -> tuple[str, dict] | None:
        """A reply with no tool calls: nudge the model to continue, or give up."""
        result = message.content or ""

        # Store assistant turn. Use result (never None) so that _messages
        # stays well-formed for all subsequent API calls.
        # DeepSeek thinking mode requires reasoning_content to be echoed back.
        asst_msg: dict = {"role": "assistant", "content": result}
        if reasoning:
            asst_msg["reasoning_content"] = reasoning
        self.log.append(
            sev.ASSISTANT_MESSAGE,
            {"turn": self.turns.turn, "step": self.turns.step, "message": asst_msg},
            surface_op="append",
        )
        self._sync_messages()
        usage = response.usage
        thinking_tok = (
            getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None)
            or 0
        )
        cached_tok = (
            getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
            or 0
        )
        self.callbacks.on_token_update(
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
            getattr(usage, "cost", None),
            thinking_tok,
            cached_tok,
        )
        self.tracker.record_assistant(
            message.content, usage, [],
            cached_tokens=cached_tok, thinking_tokens=thinking_tok,
        )

        # No tool calls — inject "continue" to prompt model to call write_handoff
        self.callbacks.on_assistant_text(result)
        if self._garbled_streak_reached(result):
            self._recover_from_garbled_loop()
            return None
        if self._continuation_count >= self.config.max_continuations:
            self._process.idle()
            self.callbacks.on_done(result)
            return result, sev.reason_max_continuations()
        self._continuation_count += 1
        self._log_user_message("user", CONTINUE_PROMPT, "continue")
        self.callbacks.on_continue_injected(
            self._continuation_count, self.config.max_continuations
        )
        return None

    def _handle_tool_reply(self, message, response, reasoning: str) -> tuple[str, dict] | None:
        """A reply with tool calls: log it, run the tools, maybe compact."""
        # A tool-call step breaks an empty-reply streak: "in a row" means
        # adjacent steps, so recovery's "revise the last N" hits only those.
        self._empty_content_streak = 0
        if message.content:
            self.callbacks.on_assistant_text(message.content)

        # One assistant message with ALL tool_calls (standard OpenAI format).
        # Splitting into per-tool-call assistant messages breaks providers that
        # enforce protocol conformance (e.g. DeepSeek thinking mode).
        asst_tc_msg: dict = {
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
        if reasoning:
            asst_tc_msg["reasoning_content"] = reasoning
        self.log.append(
            sev.ASSISTANT_MESSAGE,
            {"turn": self.turns.turn, "step": self.turns.step, "message": asst_tc_msg},
            surface_op="append",
        )
        self._sync_messages()

        prompt_tok = getattr(response.usage, "prompt_tokens", 0) or 0
        self._last_prompt_tokens = prompt_tok

        tool_records: list[ToolCallRecord] = []
        short_circuit = self._dispatch_tool_calls(message, response, tool_records)
        if short_circuit is not None:
            return short_circuit, sev.reason_completed()

        self._finalize_turn(message, response, tool_records)

        # ── Compaction trigger ────────────────────────────────────────
        if (
            self.config.context_window > 0
            and prompt_tok > 0
            and prompt_tok > self.config.context_window - self.config.reserve_tokens
        ):
            self._compact_context()
        return None

    def _garbled_streak_reached(self, reply_text: str) -> bool:
        """Count consecutive empty replies; True once they form a garbled loop."""
        if reply_text.strip():
            self._empty_content_streak = 0
            return False
        self._empty_content_streak += 1
        return self._empty_content_streak >= _EMPTY_CONTENT_THRESHOLD

    def _recover_from_garbled_loop(self) -> None:
        """Drop the empty steps and compact everything, staying in the same turn.

        The turn and the user's message are kept. The revision is saved to
        the events file like a user-driven one.
        """
        self.turns.end_step()  # close it so it can be revised
        try:
            self.revise_last_steps(self._empty_content_streak, keep_turn=True)
        except OSError as exc:
            self.callbacks.on_assistant_text(
                f"[Warning: could not save the revised session log — {exc}.]"
            )
        self.turns.resync_step()
        self._empty_content_streak = 0
        self._continuation_count = 0
        self.callbacks.on_assistant_text(
            "[Garbled response loop detected — compacting context for recovery.]"
        )
        self.callbacks.on_compaction_started()
        self.compact(summarize_all=True)

    def _keep_interrupted_text(self, response) -> None:
        """Log what an interrupted *stream* had said, so "continue" makes sense.

        Half-streamed tool calls and reasoning are dropped; a blocking response
        that arrives after the interrupt is dropped entirely.
        """
        if not self.config.stream or response is None:
            return
        text = (response.choices[0].message.content or "").strip()
        if text:
            self.log.append(
                sev.ASSISTANT_MESSAGE,
                {
                    "turn": self.turns.turn,
                    "step": self.turns.step,
                    "message": {"role": "assistant", "content": text},
                },
                surface_op="append",
            )
            self._sync_messages()

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

    # ── Side-effect handlers ────────────────────────────────────────────────

    def _handle_all_tasks_resolved(self) -> str:
        plan = self.config.active_plan_file
        return (
            f"All tasks resolved. Active plan remains associated: {plan}\n\n"
            "Next: finish any pending task commits, then run integrated verification "
            "and a final review before accepting delivery. "
            "Then return to enter-workflow for branch finishing and closure. "
            "Call set_active_plan(null) only after finishing and documentation succeed."
        )

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

    def _rebuild_for_reload(self) -> tuple[set[str], set[str], list[tuple[str, str]]]:
        """Hot-reload skills from disk, rebuild registry + system prompt."""
        from agent._reload import rebuild_for_reload

        return rebuild_for_reload(self)

    def finish(self) -> None:
        """Finalize the session — write session_end to JSONL. Called by the CLI at session end."""
        self.tracker.finish(raw_messages=self._messages)
