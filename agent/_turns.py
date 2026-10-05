"""agent/_turns.py — the one writer of turn/step boundary events.

AgentLoop.run() and the short side turns (/reload, /wtf, GUI compaction)
open and close turns only through ``TurnBoundaries``, so every exit path
leaves balanced brackets: no step left open, no turn opened inside another.
tests/test_run_contract.py checks this for every run() exit path.

Turn 0 (the replay of a resumed conversation) is written separately by
AgentLoop._seed_from_messages.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

from agent import session_events as sev

if TYPE_CHECKING:
    from agent.session_log import SessionLog


class TurnBoundaries:
    def __init__(self, log: SessionLog) -> None:
        self._log = log
        self._step = 0

    @property
    def turn(self) -> int | None:
        """The open turn, or None between turns."""
        return self._log.open_turn

    @property
    def step(self) -> int:
        """The current (or last) step number in the open turn."""
        return self._step

    def open_turn(self, **data: Any) -> int:
        turn = self._log.next_turn()
        self._log.append(sev.TURN_START, {"turn": turn, **data})
        self._step = 0
        return turn

    def start_step(self) -> int:
        self._step += 1
        self._log.append(sev.STEP_START, {"turn": self.turn, "step": self._step})
        return self._step

    def end_step(self) -> None:
        """Close the open step, if there is one."""
        if self._log.open_step is not None:
            self._log.append(sev.STEP_END, {"turn": self.turn, "step": self._log.open_step})

    def close_turn(self, reason: dict) -> None:
        """Close the open turn and any open step in it. A no-op between turns."""
        turn = self._log.open_turn
        if turn is None:
            return
        self.end_step()
        self._log.append(sev.TURN_END, {"turn": turn, "reason": reason})

    def resync_step(self) -> None:
        """Number the next step after the open turn's last remaining one.

        Needed after steps are revised out of the open turn.
        """
        last = 0
        for event in reversed(self._log.events):
            if event.branch != "main" or event.data.get("turn") != self.turn:
                continue
            if event.type == sev.TURN_START:
                break
            if event.type == sev.STEP_START:
                last = max(last, event.data["step"])
        self._step = last

    @contextmanager
    def side_turn(self, **data: Any) -> Iterator[int]:
        """A short turn outside run(): closed as completed, or as an error if the body raises."""
        turn = self.open_turn(**data)
        try:
            yield turn
        except BaseException as exc:
            self.close_turn(sev.reason_error(str(exc), type(exc).__name__))
            raise
        self.close_turn(sev.reason_completed())
