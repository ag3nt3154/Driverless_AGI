"""Ask-user broker: blocks the agent thread until Electron sends an answer."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING
from uuid import uuid4

from dagi_gui.protocol import ProtocolError

if TYPE_CHECKING:
    from dagi_gui.protocol import EventWriter


class QuestionBroker:
    """Bridge between the blocking on_ask_user callback and the async answer command.

    ask() is called from the agent worker thread and blocks until answer() is
    called from the server dispatch thread (or the timeout expires).
    """

    def __init__(self, writer: "EventWriter") -> None:
        self._writer = writer
        self._lock = threading.Condition(threading.Lock())
        self._pending_id: str | None = None
        self._answer: str | None = None

    def ask(
        self,
        question: str,
        options: list[dict],
        timeout: float | None = None,
    ) -> str:
        """Emit a question event and block until answered or timed out."""
        qid = uuid4().hex
        with self._lock:
            self._pending_id = qid
            self._answer = None

        self._writer.write(
            "question",
            question_id=qid,
            text=question,
            options=options,
        )

        with self._lock:
            self._lock.wait_for(
                lambda: self._answer is not None or self._pending_id != qid,
                timeout=timeout,
            )
            answer = self._answer
            self._pending_id = None
            self._answer = None

        if answer is not None:
            return answer
        # Timed out — return default
        return (
            next((o["label"] for o in options if o.get("recommended")), None)
            or (options[0]["label"] if options else "")
        )

    def answer(self, question_id: str, answer: str) -> None:
        """Unblock a pending ask() with the given answer."""
        with self._lock:
            if self._pending_id != question_id:
                raise ProtocolError("no pending question with that id")
            self._answer = answer
            self._lock.notify_all()

    @property
    def has_pending(self) -> bool:
        with self._lock:
            return self._pending_id is not None

    def resolve_default(self) -> None:
        """Resolve the pending question with its default (used during shutdown)."""
        with self._lock:
            if self._pending_id is not None:
                self._answer = ""
                self._lock.notify_all()
