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
from pathlib import Path
from typing import TYPE_CHECKING

from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
)

from agent import session_events as sev
from agent.protocol import LIST_ENCODING_PREFIX, SideEffect, ToolResult
from agent.session import ToolCallRecord
from agent._loop_helpers import _format_reload_notification
from tools.output_filter import filter_tool_output

if TYPE_CHECKING:
    from agent.loop import AgentLoop


def dispatch_tool_calls(
    loop: AgentLoop,
    message,
    response,
    tool_records: list[ToolCallRecord],
) -> str | None:
    """Dispatch every tool call in `message`, appending results to _messages.

    Returns a non-None string only when a tool returned SideEffect.END_TURN
    (write_handoff), in which case `run()` must return that value immediately
    without a further API turn.

    Deferred system messages are appended AFTER all tool results so they
    don't break the assistant→tool pairing that strict providers
    (e.g. DeepSeek) enforce.
    """
    deferred_system_msgs: list[str] = []

    for tc in message.tool_calls:
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
        args = json.loads(tc.function.arguments)
        result = loop.registry.dispatch(tc.function.name, args)

        # ── Typed side-effect dispatch ──────────────────────────────────────
        if isinstance(result, ToolResult) and result.side_effect is not None:
            effect = result.side_effect

            if effect is SideEffect.END_TURN:
                return handle_end_turn(
                    loop, tc, result, description, tool_records, (message, response)
                )
            elif effect is SideEffect.ENTER_PLAN_MODE:
                result = loop._handle_enter_plan_mode(
                    result.side_effect_data or args
                )
            elif effect is SideEffect.EXIT_PLAN_MODE:
                result = loop._handle_exit_plan_mode(args)
            elif effect is SideEffect.ALL_TASKS_RESOLVED:
                result = loop._handle_all_tasks_resolved()
            elif effect is SideEffect.RELOAD_SKILLS:
                added, removed, errors = loop._rebuild_for_reload()
                result = _format_reload_notification(
                    len(loop.skills), added, removed, errors
                )
                deferred_system_msgs.append(result)
            elif effect is SideEffect.SWITCH_MODEL:
                tier = (result.side_effect_data or {}).get("tier")
                result = loop._handle_switch_model(tier, args)

        # Unwrap plain ToolResult to string for bookkeeping
        if isinstance(result, ToolResult):
            result = result.output

        bookkeep_tool_call(loop, tc, result, description, tool_records)
        loop._lifecycle.tool_bookkeeping_finished()

    for _sys_content in deferred_system_msgs:
        loop._log_user_message("system", _sys_content, "reload")
    return None


def bookkeep_tool_call(
    loop: AgentLoop,
    tc: ChatCompletionMessageFunctionToolCall,
    result,
    description: str,
    tool_records: list[ToolCallRecord],
) -> str:
    """Filter, log, and record a single tool call's result, appending its
    tool message to self._messages. Shared by the normal per-tool-call
    dispatch loop and the `handle_end_turn` short-circuit path so
    the two can't drift (e.g. the list-safety conversion below must
    apply to both). Returns the full (unfiltered) result string.
    """
    # ── Output filter ────────────────────────────────────────
    context_result, full_str = filter_tool_output(
        result, loop.config.reserve_tokens, Path(loop.config.project_path)
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
    tc: ChatCompletionMessageFunctionToolCall,
    result: ToolResult,
    description: str,
    tool_records: list[ToolCallRecord],
    message_response: tuple,
) -> str:
    """Terminate the agent's turn on SideEffect.END_TURN.

    Works for both main agent and subagent — the tool itself decides
    whether to write a file or just return content.
    """
    message, response = message_response
    output = result.output

    loop.callbacks.on_handoff()
    full_str = bookkeep_tool_call(loop, tc, output, description, tool_records)
    loop._lifecycle.tool_bookkeeping_finished()
    finalize_turn(loop, message, response, tool_records)

    loop._process.idle()
    loop.callbacks.on_done(full_str)
    return full_str
