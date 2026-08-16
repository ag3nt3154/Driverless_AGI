"""agent/session_surface.py — Ordered projection of message-producing events.

The surface is the model-facing view of the session log: an ordered list of
the three surface event types, projected into OpenAI chat message dicts.
Everything else in the log — boundaries, tool calls, request headers, plan
snapshots — is log-only and costs zero tokens.

Projection is incremental. Each appended node is projected exactly once and
cached, because the alternative (re-projecting the whole history every step)
trades KV-cache hits for CPU.
"""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from agent import session_events as ev

if TYPE_CHECKING:  # pragma: no cover
    from agent.session_log import SessionEvent


def project_event(event: "SessionEvent") -> dict:
    """Project one surface event into an OpenAI chat message dict.

    Every branch deep-copies: the returned dict is handed to the provider
    client and to callbacks, both of which have historically mutated what
    they were given. The log must not be reachable through its own output.
    """
    data = event.data
    if event.type == ev.USER_MESSAGE:
        # `role` is durable data, not a projection decision — wiki context
        # and reload notices ride this event type with role="system".
        return {"role": data["role"], "content": copy.deepcopy(data["content"])}
    if event.type == ev.ASSISTANT_MESSAGE:
        return copy.deepcopy(dict(data["message"]))
    if event.type == ev.TOOL_RESULT:
        return {
            "role": "tool",
            "tool_call_id": data["call_id"],
            "content": copy.deepcopy(data["content"]),
        }
    raise ValueError(f"{event.type} is not a surface event")


class Surface:
    """Ordered surface nodes plus their cached projections.

    ``nodes`` and the message cache are kept parallel: ``_cache[i]`` is the
    projection of the event at ``_nodes[i]``.
    """

    def __init__(self) -> None:
        self._nodes: list[int] = []
        self._cache: list[dict] = []
        #: Increments on every replace. A stable generation means every
        #: previously-sent prefix is still byte-identical, so the provider's
        #: KV cache is reusable in full.
        self.generation: int = 0

    @property
    def nodes(self) -> tuple[int, ...]:
        """Surface node seq numbers, in surface order."""
        return tuple(self._nodes)

    def index_of(self, seq: int) -> int:
        """Surface position of node ``seq``. Raises KeyError if absent."""
        try:
            return self._nodes.index(seq)
        except ValueError:
            raise KeyError(f"seq {seq} is not a surface node") from None

    def accept(self, event: "SessionEvent") -> None:
        """Admit a committed surface event, honouring its ``surface_op``."""
        if event.surface_op == "append":
            self._nodes.append(event.seq)
            self._cache.append(project_event(event))
            return
        raise ValueError(f"unsupported surface_op: {event.surface_op!r}")

    def messages(self) -> list[dict]:
        """A fresh list over the cached projections."""
        return list(self._cache)
