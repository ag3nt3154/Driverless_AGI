"""Per-chat session state for the Telegram bot."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class ChatSession:
    """Holds conversation state for a single Telegram chat."""
    chat_id: int
    messages: list | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    busy: bool = False
    pending_ask: tuple[threading.Event, list] | None = None


class SessionManager:
    """Maps Telegram chat IDs to their ChatSession state."""

    def __init__(self) -> None:
        self._sessions: dict[int, ChatSession] = {}

    def get_or_create(self, chat_id: int) -> ChatSession:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = ChatSession(chat_id=chat_id)
        return self._sessions[chat_id]

    def clear(self, chat_id: int) -> None:
        if chat_id in self._sessions:
            self._sessions[chat_id] = ChatSession(chat_id=chat_id)
