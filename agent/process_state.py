from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent.expression_assets import AssetRef


class ProcessStateResolver(Protocol):
    def resolve(self, state: str) -> AssetRef: ...


@dataclass(frozen=True)
class ProcessSnapshot:
    state: str
    asset: AssetRef


class ProcessStateController:
    def __init__(self, library: ProcessStateResolver, *, on_change=None) -> None:
        self._library = library
        self._on_change = on_change or (lambda snapshot: None)
        self._snapshot: ProcessSnapshot | None = None

    @property
    def snapshot(self) -> ProcessSnapshot | None:
        return self._snapshot

    def set_listener(self, listener, *, emit_current: bool = False) -> None:
        self._on_change = listener
        if emit_current and self._snapshot is not None:
            self._on_change(self._snapshot)

    def idle(self) -> ProcessSnapshot:
        return self._transition("idle")

    def thinking(self) -> ProcessSnapshot:
        return self._transition("thinking")

    def tool_started(self, name: str) -> ProcessSnapshot:
        return self._transition(f"tool:{name}")

    def tool_ended(self) -> ProcessSnapshot:
        return self._transition("thinking")

    def paused(self) -> ProcessSnapshot:
        return self._transition("paused")

    def error(self) -> ProcessSnapshot:
        return self._transition("error")

    def _transition(self, state: str) -> ProcessSnapshot:
        snapshot = ProcessSnapshot(state=state, asset=self._library.resolve(state))
        if snapshot == self._snapshot:
            return self._snapshot
        self._snapshot = snapshot
        self._on_change(snapshot)
        return snapshot
