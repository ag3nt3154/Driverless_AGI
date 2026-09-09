"""tools/read/_reader_provider.py — Provider abstraction for the reader controller.

ReaderRuntime groups the external dependencies (API client, callbacks,
handoff tool) injected into ReaderController. The functions here are
pure transformations on those dependencies so the controller stays focused
on its sequential read loop.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from tools.read._budgets import ReaderLimits, ReaderCapacityError, require_context_fit

if TYPE_CHECKING:
    from agent._loop_config import AgentCallbacks


class ReaderCancelledError(Exception):
    """Raised when the cancellation check fires between API attempts."""


class ReaderProviderError(Exception):
    """Raised when the provider returns an unusable response (empty, tool-call,
    length-truncated) after all retries are exhausted."""


@dataclass
class ReaderRuntime:
    """External dependencies injected into ReaderController.

    None of these fields are mutable reader state; the controller owns that
    in ReaderState. ReaderRuntime is set once at construction and shared
    across the read loop.

    client           OpenAI-compatible client with .chat.completions.create().
    model            Model ID string passed to the API.
    system_prompt    System prompt injected as the first message.
    initial_messages Inherited prefix from parent context (read-only list).
    schemas          Tool schemas for the handoff tool (sent with the final call).
    callbacks        AgentCallbacks for progress events.
    handoff_tool     Object with .run(content: str) -> str for writing the handoff.
    request_options  Extra kwargs spread into .create() (e.g. temperature).
    is_cancelled     Zero-argument callable returning True if cancelled.
    api_error_retries How many times to retry transient API errors.
    """
    client: Any
    model: str
    system_prompt: str
    initial_messages: list[dict] = field(default_factory=list)
    schemas: list[dict] = field(default_factory=list)
    callbacks: Any = None
    handoff_tool: Any = None
    request_options: dict = field(default_factory=dict)
    is_cancelled: Callable[[], bool] = field(default=lambda: False)
    api_error_retries: int = 3


def build_reader_request(
    messages: list[dict],
    *,
    runtime: ReaderRuntime,
    output_tokens: int,
    include_tools: bool = False,
) -> dict:
    """Build a provider request dict from current accumulated messages.

    Parameters
    ----------
    messages
        Accumulated conversation messages (prefix + section turns so far).
        Does NOT include system prompt (passed separately as a system message).
    runtime
        Injected runtime dependencies.
    output_tokens
        max_tokens cap for this call (section budget or full final budget).
    include_tools
        True only for the final handoff call where the model needs tool access.
    """
    all_messages: list[dict] = []
    if runtime.system_prompt:
        all_messages.append({"role": "system", "content": runtime.system_prompt})
    all_messages.extend(runtime.initial_messages)
    all_messages.extend(messages)

    req: dict = {
        "model": runtime.model,
        "messages": all_messages,
        "max_tokens": output_tokens,
        **runtime.request_options,
    }

    if include_tools and runtime.schemas:
        req["tools"] = runtime.schemas
        req["tool_choice"] = "auto"

    return req


def call_reader(
    request: dict,
    *,
    runtime: ReaderRuntime,
    limits: ReaderLimits,
) -> str:
    """Pre-check fit, make the API call, return text content.

    Validates E(request) + O + M <= C before each call. Checks cancellation
    between retry attempts. Rejects empty, tool-call-only, and length-truncated
    responses before returning.

    Raises
    ------
    ReaderCapacityError
        If the request exceeds the context window.
    ReaderCancelledError
        If cancellation fires between attempts.
    ReaderProviderError
        If all retries are exhausted without a usable text response.
    """
    require_context_fit(request, limits)

    last_error: Exception | None = None
    for attempt in range(max(1, runtime.api_error_retries)):
        if runtime.is_cancelled():
            raise ReaderCancelledError("Reader cancelled before API call")

        try:
            response = runtime.client.chat.completions.create(**request)
        except Exception as exc:
            last_error = exc
            if attempt < runtime.api_error_retries - 1:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise ReaderProviderError(
                f"API error after {runtime.api_error_retries} attempts: {exc}"
            ) from exc

        choice = response.choices[0] if response.choices else None
        if choice is None:
            last_error = ReaderProviderError("No choices in response")
            continue

        finish = getattr(choice, "finish_reason", None)
        if finish == "length":
            raise ReaderProviderError(
                "Response length-truncated. Reduce section budget or chunk size."
            )

        content = getattr(choice.message, "content", None) or ""
        if not content.strip():
            last_error = ReaderProviderError("Empty content in response")
            continue

        if choice.message.tool_calls and not content.strip():
            last_error = ReaderProviderError("Tool-call-only response in section turn")
            continue

        return content

    raise ReaderProviderError(
        f"All attempts produced unusable responses: {last_error}"
    )


def emit_reader_progress(
    callbacks: Any,
    *,
    completed: int,
    total: int,
    phase: str,
) -> None:
    """Emit a status event for reader progress using existing callback shape.

    Uses on_assistant_text as a lightweight progress channel — the status
    message includes chunk index and phase without dumping source text.
    """
    if callbacks is None:
        return
    on_text = getattr(callbacks, "on_assistant_text", None)
    if callable(on_text):
        on_text(f"[reader] {phase} {completed}/{total}")
