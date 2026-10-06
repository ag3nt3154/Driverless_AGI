"""agent/_tool_dispatch.py — tool-call dispatch and bookkeeping.

Extracted verbatim from AgentLoop methods in agent/loop.py (`self` became the
explicit `loop` parameter) so the loop orchestrator stays under its size cap.
Only agent/loop.py imports from this module. Side-effect routing
(write_handoff end-turn, plan-mode transitions, task-status, reload, model
switch) lives in dispatch_tool_calls, driven by ToolResult.side_effect rather
than magic string patterns.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
)

from agent import session_events as sev
from agent.protocol import LIST_ENCODING_PREFIX, SideEffect, ToolResult
from agent.session import ToolCallRecord
from agent._loop_helpers import _format_reload_notification
from agent._model_switch import current_supports_images
from agent.image_assets import ImageAssetStore
from tools.output_filter import filter_tool_output

if TYPE_CHECKING:
    from agent.loop import AgentLoop


def _patch_logged_tool_args(loop: AgentLoop, call_id: str, safe_args: str) -> None:
    """Overwrite malformed arguments in already-logged events so the
    conversation history sent to the API contains only valid JSON.

    Patches both the TOOL_CALL event and the ASSISTANT_MESSAGE event that
    carries the ``tool_calls`` list.
    """
    from agent import session_events as _ev

    for event in reversed(loop.log._events):
        if event.type == _ev.TOOL_CALL and event.data.get("call_id") == call_id:
            event.data["arguments"] = safe_args
        if event.type == _ev.ASSISTANT_MESSAGE:
            for tc_dict in event.data.get("message", {}).get("tool_calls", []):
                if tc_dict.get("id") == call_id:
                    tc_dict["function"]["arguments"] = safe_args
            loop.log.surface.reproject(event)
            break
    loop._sync_messages()


# Tools whose result must be seen before any other action is chosen. Batched siblings
# were decided before the user's answer, so a mixed batch runs nothing at all.
SOLO_TOOLS = frozenset({"ask_user"})


def _solo_violation(tool_calls) -> str | None:
    """Name of a solo tool batched with other calls, or None if the batch is fine."""
    if len(tool_calls) < 2:
        return None
    return next((tc.function.name for tc in tool_calls if tc.function.name in SOLO_TOOLS), None)


def _skip_result(loop: AgentLoop, name: str, solo: str | None) -> str | None:
    """Result for a call that must not run (user pause, or a solo-tool batch), else None."""
    if not loop._pause_event.is_set() or loop._abort_request.is_set():
        return "[paused] Tool execution cancelled by user pause."
    if solo is None:
        return None
    if name == solo:
        return (
            f"Error: {solo} must be the only tool call in its response; nothing in this "
            "batch ran. Call it again on its own, then act on the answer."
        )
    return f"[not run: this batch contained {solo}, which must be called alone]"


@dataclass
class _Batch:
    """State shared by the calls of one assistant tool batch."""
    solo: str | None
    #: Reload notices, logged AFTER all tool results so they don't break the
    #: assistant→tool pairing that strict providers (e.g. DeepSeek) enforce.
    system_msgs: list[str] = field(default_factory=list)
    image_parts: list[dict] = field(default_factory=list)
    end_turn_result: str | None = None
    end_turn_call_id: str | None = None


def dispatch_tool_calls(
    loop: AgentLoop,
    message,
    response,
    tool_records: list[ToolCallRecord],
) -> str | None:
    """Dispatch every tool call in `message`, appending results to _messages.

    Every call in the batch is bookkept in the model's call order, so the
    transcript always pairs a call with its result; calls skipped for a user
    pause, a mixed SOLO_TOOLS batch, or an earlier END_TURN get an explanatory
    result instead of running. Returns a non-None string only when a tool
    returned SideEffect.END_TURN (write_handoff), in which case `run()` must
    return that value immediately without another API call.

    Deferred system messages are appended AFTER all tool results so they
    don't break the assistant→tool pairing that strict providers
    (e.g. DeepSeek) enforce.

    The first END_TURN call in a batch wins and is bookkept in place. Every
    later call in the batch (a redundant handoff or an ordinary tool) is not
    executed but still gets an explicit result, so each logged tool/call
    has its tool/result. The per-call event order is pinned by
    tests/test_end_turn_batch.py::TestDispatchEventTrace.
    """
    batch = _Batch(solo=_solo_violation(message.tool_calls))
    for tc in message.tool_calls:
        _dispatch_one(loop, tc, batch, tool_records)

    for _sys_content in batch.system_msgs:
        loop._log_user_message("user", _sys_content, "reload")
    if batch.image_parts:
        loop._log_user_message("user", batch.image_parts, "tool_image")

    if batch.end_turn_result is not None:
        return handle_end_turn(loop, batch.end_turn_result, tool_records, (message, response))
    return None


def _dispatch_one(
    loop: AgentLoop,
    tc: ChatCompletionMessageFunctionToolCall,
    batch: _Batch,
    tool_records: list[ToolCallRecord],
) -> None:
    """Announce, then skip or run, then bookkeep exactly one result for one call."""
    description = _announce_call(loop, tc)
    blocked = _blocked_result(loop, tc, batch)
    if blocked is not None:
        result, ends_turn = blocked, False
    else:
        result, ends_turn = _run_call(loop, tc, batch)
    full_str = bookkeep_tool_call(loop, tc, result, description, tool_records)
    if ends_turn:
        batch.end_turn_result = full_str
        batch.end_turn_call_id = tc.id
    loop._lifecycle.tool_bookkeeping_finished()


def _announce_call(loop: AgentLoop, tc: ChatCompletionMessageFunctionToolCall) -> str:
    """Publish the call's start and log it; returns its display description."""
    tool_obj = loop.registry._tools.get(tc.function.name)
    description = tool_obj.description if tool_obj else tc.function.name
    loop._lifecycle.tool_started(tc.function.name)
    loop.callbacks.on_tool_start(tc.function.name, description, tc.function.arguments)
    loop.tracker.record_tool_start(tc.function.name, description, tc.function.arguments)

    # Recorded BEFORE execution: a tool/call with no tool/result is a
    # detectable interruption, which Phase 4 crash repair depends on.
    loop.log.append(
        sev.TOOL_CALL,
        {
            "turn": loop.log.open_turn,
            "step": loop.log.open_step,
            "call_id": tc.id,
            "name": tc.function.name,
            "arguments": tc.function.arguments,  # raw, unparsed
        },
    )
    return description


def _blocked_result(
    loop: AgentLoop, tc: ChatCompletionMessageFunctionToolCall, batch: _Batch,
) -> str | None:
    """Result for a call that must not run: the turn already ended, a pause, or solo."""
    if batch.end_turn_call_id is not None:
        return (
            f"[skipped] Not executed: the turn already ended via call "
            f"{batch.end_turn_call_id} earlier in this batch."
        )
    return _skip_result(loop, tc.function.name, batch.solo)


def _parse_args(
    loop: AgentLoop, tc: ChatCompletionMessageFunctionToolCall,
) -> tuple[dict | None, str | None]:
    """Return (args, None), or (None, error) after sanitising malformed arguments."""
    try:
        return json.loads(tc.function.arguments), None
    except json.JSONDecodeError as exc:
        result = (
            f"Error: invalid JSON arguments for tool {tc.function.name!r}: {exc}"
        )
        # Sanitise the malformed arguments string so it doesn't poison
        # the conversation history and trigger a 400 on the next API call.
        _safe_args = json.dumps({"_malformed": tc.function.arguments})
        tc.function.arguments = _safe_args
        _patch_logged_tool_args(loop, tc.id, _safe_args)
        return None, result


def _run_call(
    loop: AgentLoop, tc: ChatCompletionMessageFunctionToolCall, batch: _Batch,
) -> tuple[object, bool]:
    """Execute one call; returns (result to bookkeep, whether it ends the turn)."""
    args, error = _parse_args(loop, tc)
    if error is not None:
        return error, False
    result = loop.registry.dispatch(tc.function.name, args)

    # ── Typed side-effect dispatch ──────────────────────────────────────
    if isinstance(result, ToolResult) and result.side_effect is SideEffect.END_TURN:
        # on_handoff must precede on_tool_end so UIs suppress the
        # handoff's tool card and render it as the final answer.
        loop.callbacks.on_handoff()
        return result.output, True
    if isinstance(result, ToolResult) and result.side_effect is not None:
        result = _apply_side_effect(loop, result, args, batch)

    # Unwrap plain ToolResult to string for bookkeeping
    if isinstance(result, ToolResult):
        result = result.output
    return result, False


def _apply_side_effect(loop: AgentLoop, result: ToolResult, args: dict, batch: _Batch):
    """Route a non-END_TURN side effect; returns the result to report for the call."""
    effect = result.side_effect
    if effect is SideEffect.ALL_TASKS_RESOLVED:
        return loop._handle_all_tasks_resolved()
    if effect is SideEffect.RELOAD_SKILLS:
        added, removed, errors = loop._rebuild_for_reload()
        notice = _format_reload_notification(len(loop.skills), added, removed, errors)
        batch.system_msgs.append(notice)
        return notice
    if effect is SideEffect.SWITCH_MODEL:
        tier = (result.side_effect_data or {}).get("tier")
        return loop._handle_switch_model(tier, args)
    if effect is SideEffect.SET_ACTIVE_PLAN:
        loop.config.active_plan_file = (result.side_effect_data or {}).get("path")
        return result.output
    if effect is SideEffect.ATTACH_IMAGE:
        return _attach_image(loop, result, batch.image_parts)
    return result


def _attach_image(loop: AgentLoop, result: ToolResult, parts: list[dict]) -> str:
    """Queue a tool-read image for the follow-up user message.

    Chat Completions tool messages are text-only, so the image rides in a
    user message logged after every tool result of the step. Only a model
    explicitly configured with ``supports_images: true`` gets it: an
    unknown model that rejects images would fail every later request,
    since the image stays in history.
    """
    data = result.side_effect_data or {}
    path = data.get("path", "")
    if current_supports_images(loop) is not True:
        name = loop.config.display_name or loop.config.model
        return (
            f"Error (DAGI_CANNOT_PROCESS): cannot view image '{path}' — the current "
            f"model ({name}) is not configured as multimodal. If it accepts images, "
            f"set `supports_images: true` in its model config."
        )
    ref = ImageAssetStore(loop.config.project_path).store(data["image"])
    parts.append({"type": "text", "text": f"[Image from read: {path}]"})
    parts.append(ref.to_content_part())
    return result.output


def bookkeep_tool_call(
    loop: AgentLoop,
    tc: ChatCompletionMessageFunctionToolCall,
    result,
    description: str,
    tool_records: list[ToolCallRecord],
) -> str:
    """Filter, log, and record a single tool call's result, appending its
    tool message to self._messages. Called for every call of a batch —
    ordinary tools and END_TURN handoffs alike — so a call can never reach
    the transcript without its result (the list-safety conversion below
    applies to all of them). Returns the full (unfiltered) result string.
    """
    # ── Output filter ────────────────────────────────────────
    context_result, full_str = filter_tool_output(
        result, loop.config.reserve_tokens, Path(loop.config.project_path),
        edge_chars=loop.config.truncate_edge_chars,
    )
    if context_result is not result:
        # Filtering fired — warn the user via the assistant text stream
        loop.callbacks.on_assistant_text(
            f"[output filter] Tool result was large and has been truncated. "
            f"Full output saved under "
            f"{Path(loop.config.project_path) / '.dagi' / 'hash_cache' / 'tool_output'}."
        )
    # ─────────────────────────────────────────────────────────
    result_str = (
        context_result if isinstance(context_result, str)
        else LIST_ENCODING_PREFIX + json.dumps(context_result)
    )
    loop.callbacks.on_tool_end(tc.function.name, result_str)   # filtered
    loop.tracker.record_tool_end(tc.function.name, full_str)    # full (JSONL)

    tool_records.append(ToolCallRecord(
        name=tc.function.name,
        description=description,
        input=tc.function.arguments,
        result=full_str,                                        # full (JSONL)
    ))
    loop.log.append(
        sev.TOOL_RESULT,
        {
            "turn": loop.log.open_turn,
            "step": loop.log.open_step,
            "call_id": tc.id,
            "content": context_result,
            "meta": None,
        },
        surface_op="append",
    )
    loop._sync_messages()
    return full_str


def finalize_turn(loop: AgentLoop, message, response, tool_records: list[ToolCallRecord]) -> None:
    """Record the assistant turn and emit the token-usage callback.

    Shared by the end of the normal per-tool-call loop and the
    `handle_end_turn` short-circuit path.
    """
    _thinking_tok = (
        getattr(getattr(response.usage, "completion_tokens_details", None), "reasoning_tokens", None)
        or 0
    )
    _cached_tok = (
        getattr(getattr(response.usage, "prompt_tokens_details", None), "cached_tokens", None)
        or 0
    )
    loop.tracker.record_assistant(
        message.content, response.usage, tool_records,
        cached_tokens=_cached_tok, thinking_tokens=_thinking_tok,
    )
    loop.callbacks.on_token_update(
        getattr(response.usage, "prompt_tokens", 0) or 0,
        getattr(response.usage, "completion_tokens", 0) or 0,
        getattr(response.usage, "cost", None),
        _thinking_tok,
        _cached_tok,
    )


def handle_end_turn(
    loop: AgentLoop,
    full_str: str,
    tool_records: list[ToolCallRecord],
    message_response: tuple,
) -> str:
    """Terminate the agent's turn on SideEffect.END_TURN.

    Called after every call in the batch has been bookkept, so the final
    callback fires only once the conversation is fully paired. Works for
    both main agent and subagent — the tool itself decides whether to
    write a file or just return content.
    """
    message, response = message_response
    finalize_turn(loop, message, response, tool_records)

    loop._process.idle()
    loop.callbacks.on_done(full_str)
    return full_str
