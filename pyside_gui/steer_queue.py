"""Typing while the agent runs: messages queued for the running turn.

A message sent mid-run shows as a dim "Queued" bubble pinned below the live
turn and is handed to ``AgentLoop.steer``, which logs it at the loop's next
checkpoint (after the current tool calls, before the next model call). When
``on_user_injected`` confirms that, the bubble joins the timeline where the
message actually entered the conversation.

Anything never confirmed — the turn ended before another checkpoint, or the
loop was still starting — is sent as the next turn once the worker finishes.
The ✕ on a queued bubble withdraws it before delivery.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import count

from PySide6.QtCore import QObject, Signal

from agent.user_input import UserSubmission


@dataclass
class _Queued:
    queue_id: str
    submission: UserSubmission


def combine(submissions: list[UserSubmission]) -> UserSubmission:
    """Leftover queued messages become one next-turn message, in order."""
    text = "\n\n".join(s.text for s in submissions if s.text.strip())
    images = tuple(img for s in submissions for img in s.images)
    return UserSubmission(text=text, images=images)


class SteerQueue(QObject):
    #: Emitted from the worker thread when its turn has finished; delivered
    #: on the GUI thread (queued connection) after any pending injections.
    turn_finished = Signal()

    def __init__(self, win) -> None:
        super().__init__()
        self._win = win
        self._items: list[_Queued] = []
        self._ids = count(1)
        win._bridge.user_injected.connect(self._on_injected)
        win._conversation.queued_cancel_requested.connect(self.cancel)
        self.turn_finished.connect(self._flush)

    @classmethod
    def for_window(cls, win) -> "SteerQueue":
        queue = getattr(win, "_steer_queue", None)
        if queue is None:
            queue = win._steer_queue = cls(win)
        return queue

    @property
    def pending(self) -> list[UserSubmission]:
        return [item.submission for item in self._items]

    def submit(self, submission: UserSubmission) -> None:
        item = _Queued(f"q{next(self._ids)}", submission)
        self._items.append(item)
        from pyside_gui._dispatch import _display_text

        self._win._conversation.append_queued_message(item.queue_id, _display_text(submission))
        loop = self._win._current_loop_ref[0] if self._win._current_loop_ref else None
        if loop is not None:
            loop.steer(submission)  # False: not running yet/anymore — flushed later

    def cancel(self, queue_id: str) -> None:
        item = next((i for i in self._items if i.queue_id == queue_id), None)
        if item is None:
            return
        loop = self._win._current_loop_ref[0] if self._win._current_loop_ref else None
        if loop is not None and not loop.cancel_steer(item.submission) and loop._in_run:
            # Already logged: the model has it, so it can't be withdrawn.
            return
        self._items.remove(item)
        self._win._conversation.remove_queued_message(queue_id)

    def _on_injected(self, submission: object) -> None:
        item = next((i for i in self._items if i.submission is submission), None)
        if item is None:
            return  # e.g. an inject_and_resume message, already shown
        self._items.remove(item)
        self._win._conversation.mark_queued_delivered(item.queue_id)

    def _flush(self) -> None:
        """Turn over: send whatever never reached the model as the next turn."""
        worker = self._win._worker
        if worker is not None:
            worker.join(timeout=2.0)  # emitted from its finally; it is exiting
        if not self._items or (worker is not None and worker.is_alive()):
            return
        items, self._items = self._items, []
        for item in items:
            self._win._conversation.mark_queued_delivered(item.queue_id)
        from pyside_gui._dispatch import dispatch_agent

        dispatch_agent(self._win, combine([i.submission for i in items]), show=False)
