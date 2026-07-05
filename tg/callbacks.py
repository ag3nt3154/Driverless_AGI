"""Build AgentCallbacks wired to Telegram message delivery."""
from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from agent.loop import AgentCallbacks

from .session import ChatSession
from .utils import chunk_message, format_ask_options

if TYPE_CHECKING:
    from telegram import Bot


def build_callbacks(
    bot: Bot,
    chat_id: int,
    session: ChatSession,
    event_loop: asyncio.AbstractEventLoop,
) -> AgentCallbacks:
    """Build AgentCallbacks that relay agent output to a Telegram chat."""

    def _send(text: str) -> None:
        """Send a message from the sync agent thread to the async Telegram bot."""
        for chunk in chunk_message(text):
            future = asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id=chat_id, text=chunk),
                event_loop,
            )
            future.result(timeout=30)

    def _send_typing() -> None:
        from telegram.constants import ChatAction
        future = asyncio.run_coroutine_threadsafe(
            bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING),
            event_loop,
        )
        try:
            future.result(timeout=10)
        except Exception:
            pass

    def on_assistant_text(text: str) -> None:
        if text.strip():
            _send(text)

    def on_tool_start(_name: str, _desc: str, _args: str) -> None:
        _send_typing()

    def on_error(exc: Exception) -> None:
        _send(f"Error: {exc}")

    def on_ask_user(
        question: str, options: list[dict], timeout: float | None
    ) -> str:
        formatted = format_ask_options(question, options)
        _send(formatted)

        evt = threading.Event()
        container: list[str] = []
        session.pending_ask = (evt, container)

        safety = (timeout + 60) if timeout is not None else 600
        evt.wait(timeout=safety)
        session.pending_ask = None

        if container:
            answer = container[0]
            if answer.isdigit():
                idx = int(answer) - 1
                if 0 <= idx < len(options):
                    return options[idx]["label"]
            return answer

        return next(
            (o["label"] for o in options if o.get("recommended")),
            options[0]["label"] if options else "",
        )

    return AgentCallbacks(
        on_tool_start=on_tool_start,
        on_tool_end=lambda _n, _r: None,
        on_assistant_text=on_assistant_text,
        on_token_update=lambda _i, _o, _c, _t=0: None,
        on_iteration=lambda _: None,
        on_done=lambda _: None,
        on_error=on_error,
        on_api_call=lambda _: None,
        on_reasoning=lambda _: None,
        on_compaction=lambda _k, _r: None,
        on_model_switch=lambda _f, _t: None,
        on_ask_user=on_ask_user,
        on_pause=lambda: None,
        supports_pause=False,
    )
