"""agent/session_log.py — Append-only session event log.

The log is the source of truth for a DAGI conversation; the LLM message list
is a projection of it (see ``agent/session_surface.py``). Every event carries
``{turn, step}`` coordinates, so structure is *stored* rather than inferred
from message order — which is what three separate orphaned-message bugs came
from (see AGENTS.md Errors Log, 2026-08-07 and 2026-08-08).

Invariants are enforced at *write* time, not tolerated at read time: a
violation raises :class:`InvariantError` at the append that caused it, where
the stack trace still names the culprit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from agent import session_events as ev

#: How an event entered the ordered surface.
#: ``"append"`` — added to the tail (the normal path).
#: ``("replace", start, end)`` — shadows surface nodes ``start``..``end``
#: inclusive, both of which must currently be on the surface.
SurfaceOp = str | tuple[str, int, int]


class InvariantError(RuntimeError):
    """A session-log invariant was violated at append time."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot_json(value: Any) -> Any:
    """Validate and deep-copy a JSON value in one pass.

    Returns the copy. Raises :class:`InvariantError` if ``value`` contains
    anything the durable log cannot represent. Copying matters: callers
    routinely hand us dicts they go on to mutate.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise InvariantError(f"event data is not JSON-serialisable: {value!r}")
        return value
    if isinstance(value, (list, tuple)):
        return [_snapshot_json(item) for item in value]
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvariantError(f"event data is not JSON-serialisable: key {key!r}")
            out[key] = _snapshot_json(item)
        return out
    raise InvariantError(f"event data is not JSON-serialisable: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """One immutable entry in the append-only log."""

    seq: int
    time: str
    type: str
    data: Mapping[str, Any]
    surface_op: SurfaceOp | None = None
    source_seqs: tuple[int, ...] | None = None
    ignorable: bool = False

    def to_json(self) -> dict:
        """Serialise for JSONL persistence. Absent optionals are omitted."""
        raw: dict = {
            "seq": self.seq,
            "time": self.time,
            "type": self.type,
            "data": self.data,
        }
        if self.surface_op is not None:
            raw["surface_op"] = (
                self.surface_op
                if isinstance(self.surface_op, str)
                else list(self.surface_op)
            )
        if self.source_seqs is not None:
            raw["source_seqs"] = list(self.source_seqs)
        if self.ignorable:
            raw["ignorable"] = True
        return raw

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "SessionEvent":
        """Rebuild an event from its JSONL form."""
        op = raw.get("surface_op")
        if isinstance(op, list):
            op = (op[0], op[1], op[2])
        seqs = raw.get("source_seqs")
        return cls(
            seq=raw["seq"],
            time=raw["time"],
            type=raw["type"],
            data=raw["data"],
            surface_op=op,
            source_seqs=tuple(seqs) if seqs is not None else None,
            ignorable=bool(raw.get("ignorable", False)),
        )


class SessionLog:
    """Append-only event log with write-time invariant enforcement."""

    def __init__(self, seed: Sequence[SessionEvent] = ()) -> None:
        self._events: list[SessionEvent] = list(seed)
        self._seq: int = self._events[-1].seq if self._events else 0

    @property
    def seq(self) -> int:
        """The sequence number of the most recent event (0 when empty)."""
        return self._seq

    @property
    def events(self) -> tuple[SessionEvent, ...]:
        """Immutable snapshot of the whole log."""
        return tuple(self._events)

    def append(
        self,
        type: str,
        data: Mapping[str, Any],
        *,
        surface_op: SurfaceOp | None = None,
        source_seqs: Sequence[int] | None = None,
        ignorable: bool = False,
    ) -> SessionEvent:
        """Validate, snapshot, and commit one event. Returns the committed event."""
        if type not in ev.KNOWN_EVENT_TYPES:
            raise InvariantError(f"unknown event type: {type!r}")
        snapshot = _snapshot_json(dict(data))
        event = SessionEvent(
            seq=self._seq + 1,
            time=_now(),
            type=type,
            data=snapshot,
            surface_op=surface_op,
            source_seqs=tuple(source_seqs) if source_seqs is not None else None,
            ignorable=ignorable,
        )
        self._events.append(event)
        self._seq = event.seq
        return event
