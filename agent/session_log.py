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
from typing import Any, Callable, Mapping, Sequence

from agent import session_events as ev
from agent.session_surface import Surface

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




def _check_surface_op_presence(type: str, surface_op: SurfaceOp | None) -> None:
    """Invariant 3: surface_op is present on surface types, absent otherwise."""
    is_surface = type in ev.SURFACE_EVENT_TYPES
    if is_surface and surface_op is None:
        raise InvariantError(f"{type} requires surface_op")
    if not is_surface and surface_op is not None:
        raise InvariantError(f"{type} is log-only and must not carry surface_op")


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
    branch: str = "main"

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
        if self.branch != "main":
            raw["branch"] = self.branch
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
            branch=raw.get("branch", "main"),
        )


class SessionLog:
    """Append-only event log with write-time invariant enforcement."""

    def __init__(self, seed: Sequence[SessionEvent] = ()) -> None:
        self._events: list[SessionEvent] = []
        self._seq: int = 0
        self._open_turn: int | None = None
        self._open_step: int | None = None
        self._max_turn: int = 0
        self._calls: dict[str, tuple[int, int]] = {}  # call_id -> (turn, step)
        self._branches: dict[str, tuple[str, int, int]] = {}  # branch_id -> (parent_branch, turn, step)
        self._surface = Surface()
        #: Optional durability sink, called once per committed event. Set by
        #: AgentLoop; None in tests so the log stays a pure in-memory object.
        #: Fires after _absorb so the sink sees a fully consistent log state.
        #: A rejected append (failed validation) never reaches this hook.
        self.on_append: Callable[[SessionEvent], None] | None = None
        for event in seed:
            self._events.append(event)
            self._seq = event.seq
            if event.branch == "main":
                self._absorb(event)

    @property
    def seq(self) -> int:
        """The sequence number of the most recent event (0 when empty)."""
        return self._seq

    @property
    def events(self) -> tuple[SessionEvent, ...]:
        """Immutable snapshot of the whole log."""
        return tuple(self._events)

    @property
    def open_turn(self) -> int | None:
        """Turn number of the currently-open turn, or None between turns."""
        return self._open_turn

    @property
    def open_step(self) -> int | None:
        """Step number of the currently-open step, or None between steps."""
        return self._open_step

    def next_turn(self) -> int:
        """The next turn number, derived from the log.

        Deliberately derived rather than held in a private counter: a resumed
        process reading a seed must not be able to desync from its own history.
        """
        return self._max_turn + 1

    @property
    def branches(self) -> dict[str, tuple[str, int, int]]:
        """Registered branches: branch_id -> (parent_branch, fork_turn, fork_step)."""
        return dict(self._branches)

    def branch_events(self, branch: str) -> list[SessionEvent]:
        """Return all events belonging to the given branch."""
        return [e for e in self._events if e.branch == branch]

    def branch_event(self, branch_id: str) -> SessionEvent | None:
        """Return the BRANCH_START event for a branch, or None."""
        for event in self._events:
            if event.type == ev.BRANCH_START and event.data.get("branch") == branch_id:
                return event
        return None

    def _absorb(self, event: SessionEvent) -> None:
        """Fold one committed event into the log's derived state."""
        if event.type == ev.TURN_START:
            self._open_turn = event.data["turn"]
            self._max_turn = max(self._max_turn, event.data["turn"])
        elif event.type == ev.TURN_END:
            self._open_turn = None
            self._open_step = None
        elif event.type == ev.STEP_START:
            self._open_step = event.data["step"]
        elif event.type == ev.STEP_END:
            self._open_step = None
        elif event.type == ev.TOOL_CALL:
            self._calls[event.data["call_id"]] = (event.data["turn"], event.data["step"])
        elif event.type == ev.BRANCH_START:
            self._branches[event.data["branch"]] = (
                event.data["parent_branch"], event.data["turn"], event.data["step"],
            )
        if event.surface_op is not None:
            self._surface.accept(event)

    @property
    def surface(self) -> Surface:
        """The ordered model-facing projection of this log."""
        return self._surface

    def derive_messages(self) -> list[dict]:
        """The LLM message history, derived from the surface.

        Does NOT include the system prompt: that lives in the request
        envelope and is reconstructed from the latest ``request/header``.
        """
        return self._surface.messages()

    def latest_header(self) -> Mapping[str, Any] | None:
        """The most recent ``request/header`` payload, or None.

        Reconstruction reads this rather than replaying every header: the
        envelope is last-write-wins state, not an accumulating sequence.
        """
        for event in reversed(self._events):
            if event.type == ev.REQUEST_HEADER:
                return event.data
        return None

    def _check_replace(
        self,
        surface_op: SurfaceOp | None,
        source_seqs: Sequence[int] | None,
    ) -> None:
        """Invariant 4: a replace cites exactly the nodes it shadows."""
        if not isinstance(surface_op, tuple) or surface_op[0] != "replace":
            return
        _, start, end = surface_op
        live = self._surface.nodes
        for edge in (start, end):
            if edge not in live:
                raise InvariantError(f"replace edge {edge} is not a live surface node")
        lo, hi = self._surface.index_of(start), self._surface.index_of(end)
        shadowed = set(live[lo:hi + 1])
        cited = set(source_seqs or ())
        if not shadowed <= cited:
            raise InvariantError(
                f"replace must cite every shadowed node; missing {sorted(shadowed - cited)}"
            )

    def _check_tool_pairing(self, data: Mapping[str, Any]) -> None:
        """Invariant 6: a tool/result names a tool/call from the same step."""
        located = self._calls.get(data["call_id"])
        if located is None:
            raise InvariantError(f"tool/result has no matching tool/call: {data['call_id']}")
        if located != (data["turn"], data["step"]):
            raise InvariantError(
                f"tool/result turn/step mismatch for {data['call_id']}: "
                f"call at {located}, result at {(data['turn'], data['step'])}"
            )

    def _check_boundaries(self, type: str, data: Mapping[str, Any]) -> None:
        """Invariants 2, 5, 6: turn enclosure, bracket sanity, tool pairing."""
        if type == ev.TURN_START and self._open_turn is not None:
            raise InvariantError(f"turn {self._open_turn} is already open")
        if type == ev.TURN_END and self._open_turn is None:
            raise InvariantError("turn/end with no open turn")
        if type in ev.SURFACE_EVENT_TYPES and self._open_turn is None:
            raise InvariantError(f"{type} appended outside an open turn")
        if type == ev.TOOL_RESULT:
            self._check_tool_pairing(data)

    def append(
        self,
        type: str,
        data: Mapping[str, Any],
        *,
        surface_op: SurfaceOp | None = None,
        source_seqs: Sequence[int] | None = None,
        ignorable: bool = False,
        branch: str = "main",
    ) -> SessionEvent:
        """Validate, snapshot, and commit one event. Returns the committed event."""
        if type not in ev.KNOWN_EVENT_TYPES:
            raise InvariantError(f"unknown event type: {type!r}")
        _check_surface_op_presence(type, surface_op)
        if branch == "main":
            self._check_boundaries(type, data)
            self._check_replace(surface_op, source_seqs)
        if type == ev.BRANCH_START:
            if branch != "main":
                raise InvariantError("BRANCH_START must be appended on the main branch")
            branch_id = data["branch"]
            if branch_id == "main":
                raise InvariantError("'main' is a reserved branch name")
            if branch_id in self._branches:
                raise InvariantError(f"branch {branch_id!r} already exists")
        snapshot = _snapshot_json(dict(data))
        event = SessionEvent(
            seq=self._seq + 1,
            time=_now(),
            type=type,
            data=snapshot,
            surface_op=surface_op,
            source_seqs=tuple(source_seqs) if source_seqs is not None else None,
            ignorable=ignorable,
            branch=branch,
        )
        self._events.append(event)
        self._seq = event.seq
        if branch == "main":
            self._absorb(event)
        if self.on_append is not None:
            self.on_append(event)
        return event
