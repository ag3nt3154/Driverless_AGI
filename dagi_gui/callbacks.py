"""Translate AgentCallbacks into GUI protocol events."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable

from agent.loop import AgentCallbacks

if TYPE_CHECKING:
    from dagi_gui.interaction import QuestionBroker
    from dagi_gui.protocol import EventWriter


def build_gui_callbacks(
    writer: "EventWriter",
    broker: "QuestionBroker",
) -> AgentCallbacks:
    """Return AgentCallbacks wired to emit NDJSON events via writer."""

    def on_tool_start(name: str, desc: str, args: str) -> None:
        writer.write("tool_start", name=name, description=desc, args=args)

    def on_tool_end(name: str, result: str) -> None:
        writer.write("tool_end", name=name, result_length=len(result))

    def on_assistant_text(text: str) -> None:
        if text.strip():
            writer.write("assistant_message", text=text)

    def on_reasoning(text: str) -> None:
        if text.strip():
            writer.write("reasoning_message", text=text)

    def on_token_update(
        inp: int, out: int, cost: float | None, thinking: int = 0, cached: int = 0
    ) -> None:
        writer.write(
            "token_update",
            input=inp, output=out, cost=cost,
            thinking=thinking, cached=cached,
        )

    def on_iteration(count: int) -> None:
        writer.write("iteration", count=count)

    def on_done(result: str) -> None:
        writer.write("turn_done", result=result)

    def on_error(exc: Exception) -> None:
        writer.write("error", message=str(exc))

    def on_api_call(messages: list) -> None:
        writer.write("context_update", message_count=len(messages))

    def on_compaction(kept: int, removed: int) -> None:
        writer.write("compaction", kept=kept, removed=removed)

    def on_model_switch(from_model: str, to_model: str) -> None:
        writer.write("model_switch", from_model=from_model, to_model=to_model)

    def on_emote(name: str, display: str, is_named: bool) -> None:
        writer.write("emote", name=name, display=display, is_named=is_named)

    def on_pause() -> None:
        writer.write("status", state="paused")

    def on_continue_injected(current: int, maximum: int) -> None:
        writer.write("continuation", current=current, maximum=maximum)

    def on_plan_shown() -> None:
        writer.write("plan_ready")

    def on_stream_start() -> None:
        writer.write("stream_start")

    def on_stream_end() -> None:
        writer.write("stream_end")

    def on_assistant_text_delta(text: str) -> None:
        writer.write("stream_delta", kind="assistant", text=text)

    def on_reasoning_delta(text: str) -> None:
        writer.write("stream_delta", kind="reasoning", text=text)

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
            writer.write("subagent_event", subagent_type=subagent_type, event=event)

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
