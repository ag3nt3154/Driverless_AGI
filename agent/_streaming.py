"""agent/_streaming.py — streaming chat-completions consumer.

Extracted verbatim from AgentLoop._consume_stream in agent/loop.py
(`self.callbacks` became the explicit `callbacks` parameter) so the loop
orchestrator stays under the 500-line cap. Only agent/loop.py imports from
this module.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent._loop_config import AgentCallbacks


def consume_stream(
    stream,
    callbacks: AgentCallbacks,
) -> "tuple[SimpleNamespace, object | None]":
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
    callbacks.on_stream_start()
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
                callbacks.on_assistant_text_delta(piece)

            # OpenRouter sends `reasoning`; DeepSeek sends `reasoning_content`;
            # SDK may park unknown keys in model_extra.
            r = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
            if not r:
                extras = getattr(delta, "model_extra", None) or {}
                r = extras.get("reasoning") or extras.get("reasoning_content") or ""
            if r:
                reasoning_parts.append(r)
                callbacks.on_reasoning_delta(r)

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
        callbacks.on_stream_end()

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
