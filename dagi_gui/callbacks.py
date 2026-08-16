"""Translate AgentCallbacks into GUI protocol events.

Event types emitted here MUST match the Zod discriminated union in
desktop/src/shared/protocol.ts — the TypeScript parseEvent() silently
drops anything with an unrecognised 'type' field.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from agent.loop import AgentCallbacks

if TYPE_CHECKING:
    from dagi_gui.interaction import QuestionBroker
    from dagi_gui.protocol import EventWriter


def build_gui_callbacks(
    writer: "EventWriter",
    broker: "QuestionBroker",
) -> AgentCallbacks:
    """Return AgentCallbacks wired to emit NDJSON events via writer."""

    # Track tool call IDs to correlate tool_call → tool_result
    _pending_tool_ids: dict[str, str] = {}  # tool_name → call_id
    _iteration_count = 0

    def on_tool_start(name: str, desc: str, args: str) -> None:
        call_id = uuid4().hex[:12]
        _pending_tool_ids[name] = call_id
        try:
            input_obj = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            input_obj = {"raw": args}
        writer.write("tool_call", tool=name, call_id=call_id, input=input_obj)

    def on_tool_end(name: str, result: str) -> None:
        call_id = _pending_tool_ids.pop(name, f"{name}-{uuid4().hex[:8]}")
        writer.write("tool_result", call_id=call_id, content=result, is_error=False)

    def on_assistant_text(text: str) -> None:
        if text.strip():
            writer.write("token", text=text)

    def on_reasoning(text: str) -> None:
        if text.strip():
            writer.write("thinking", text=text)

    def on_token_update(
        inp: int, out: int, cost: float | None, thinking: int = 0, cached: int = 0
    ) -> None:
        writer.write(
            "cost_update",
            total_usd=cost or 0.0,
            session_tokens=inp + out + thinking,
        )

    def on_iteration(count: int) -> None:
        nonlocal _iteration_count
        _iteration_count = count
        writer.write("turn_start", turn=count)

    def on_done(result: str) -> None:
        writer.write("turn_end", final_text=result)
        writer.write("task_complete")

    def on_error(exc: Exception) -> None:
        writer.write("error", message=str(exc))

    def on_api_call(messages: list) -> None:
        pass  # No TS handler; cost_update covers token info

    def on_compaction(kept: int, removed: int) -> None:
        writer.write("compact", kept=kept, removed=removed)

    def on_model_switch(from_model: str, to_model: str) -> None:
        pass  # Not in TS schema yet

    def on_emote(name: str, display: str, is_named: bool) -> None:
        pass  # Not in TS schema yet

    def on_pause() -> None:
        pass  # Status handled by session controller

    def on_continue_injected(current: int, maximum: int) -> None:
        pass  # Not in TS schema yet

    def on_plan_shown() -> None:
        pass  # Not in TS schema yet

    def on_stream_start() -> None:
        pass  # Streaming deltas are sent as token/thinking

    def on_stream_end() -> None:
        pass  # turn_end covers this

    def on_assistant_text_delta(text: str) -> None:
        if text:
            writer.write("token", text=text)

    def on_reasoning_delta(text: str) -> None:
        if text:
            writer.write("thinking", text=text)

    def on_ask_user(
        question: str, options: list, timeout: float | None
    ) -> str:
        return broker.ask(question, options, timeout=timeout)

    def on_subagent_event_factory(
        subagent_type: str,
    ) -> Callable[[str], None]:
        def relay(line: str) -> None:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"type": "raw", "content": line}
            writer.write("subagent", subagent_type=subagent_type, event=event)

        return relay

    return AgentCallbacks(
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
        on_assistant_text=on_assistant_text,
        on_token_update=on_token_update,
        on_iteration=on_iteration,
        on_done=on_done,
        on_error=on_error,
        on_api_call=on_api_call,
        on_reasoning=on_reasoning,
        on_compaction=on_compaction,
        on_model_switch=on_model_switch,
        on_ask_user=on_ask_user,
        on_emote=on_emote,
        on_subagent_event_factory=on_subagent_event_factory,
        on_pause=on_pause,
        supports_pause=True,
        on_continue_injected=on_continue_injected,
        on_plan_shown=on_plan_shown,
        on_stream_start=on_stream_start,
        on_stream_end=on_stream_end,
        on_assistant_text_delta=on_assistant_text_delta,
        on_reasoning_delta=on_reasoning_delta,
    )
