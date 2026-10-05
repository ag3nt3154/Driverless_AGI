"""agent/_request_executor.py — one model request, with its retry policy.

Extracted from the inner retry loop of AgentLoop.run so the policy can be
tested without a whole loop. The executor knows nothing about request
building, compaction or streaming: ``send`` performs one attempt and returns
a chat-completions-shaped response (``.choices[0].message``, ``.usage``).

Two classes of failure are retried, each with its own counter:

1. Transient API errors (429/500/502/503, connection, timeout) — exponential
   backoff. When retries run out the session is paused if the frontend
   supports it; otherwise the error propagates.
2. Ghost responses (HTTP 200, no content, no tool calls, zero prompt tokens)
   — instant retry with identical context.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

import httpx
import openai

if TYPE_CHECKING:
    from agent._loop_config import AgentCallbacks

TRANSIENT_STATUS_CODES = (429, 500, 502, 503)


class RequestOutcome(Enum):
    RESPONSE = "response"              # a usable response
    ABORTED = "aborted"                # interrupted; response may be partial or None
    PAUSED = "paused"                  # transient-error retries exhausted, session paused
    NULL_EXHAUSTED = "null_exhausted"  # ghost-response retries exhausted


@dataclass(frozen=True)
class RequestResult:
    outcome: RequestOutcome
    response: Any = None
    null_retries: int = 0


def is_ghost_response(response) -> bool:
    message = response.choices[0].message
    prompt_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
    return (
        not message.tool_calls
        and not (message.content or "").strip()
        and prompt_tokens == 0
    )


@dataclass
class RequestExecutor:
    send: Callable[[], Any]
    abort: threading.Event
    callbacks: AgentCallbacks
    pause: Callable[[], None]
    api_error_retries: int
    null_response_retries: int
    on_attempt: Callable[[], None] = lambda: None

    def execute(self) -> RequestResult:
        null_retries = 0
        error_retries = 0
        response = None
        while True:
            if self.abort.is_set():
                return RequestResult(RequestOutcome.ABORTED, response)  # e.g. during back-off
            self.on_attempt()
            try:
                response = self.send()
            except (openai.APIConnectionError, openai.APITimeoutError, httpx.HTTPError) as exc:
                error, label = exc, "Connection error"
            except openai.APIStatusError as exc:
                if exc.status_code not in TRANSIENT_STATUS_CODES:
                    raise
                error, label = exc, f"Server error {exc.status_code}"
            else:
                if self.abort.is_set():
                    # Interrupted: skip the ghost check, keep partial text.
                    return RequestResult(RequestOutcome.ABORTED, response)
                if not is_ghost_response(response):
                    return RequestResult(RequestOutcome.RESPONSE, response)
                null_retries += 1
                if null_retries >= self.null_response_retries:
                    return RequestResult(RequestOutcome.NULL_EXHAUSTED, response, null_retries)
                continue

            error_retries += 1
            if error_retries >= self.api_error_retries:
                if not self.callbacks.supports_pause:
                    raise error
                self.callbacks.on_assistant_text(
                    f"[{label} — all {error_retries} retries failed. "
                    "Session paused. Send a message to retry.]"
                )
                self.pause()
                self.callbacks.on_pause()
                return RequestResult(RequestOutcome.PAUSED, response)
            delay = min(2 ** error_retries, 60)
            self.callbacks.on_assistant_text(
                f"[{label}. Retrying in {delay}s "
                f"({error_retries}/{self.api_error_retries})...]"
            )
            time.sleep(delay)
