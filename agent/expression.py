from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .expression_assets import AssetRef, ImageAsset


@dataclass(frozen=True)
class ExpressionConfig:
    interval: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.interval) or self.interval < 0:
            raise ValueError("expression interval must be finite and non-negative")


@dataclass(frozen=True)
class ExpressionSnapshot:
    emote_id: str
    asset: AssetRef
    meme_asset: ImageAsset | None = None


class RandomEmoteResolver(Protocol):
    def choose(self, current_id: str | None) -> tuple[str, AssetRef]: ...


class ExpressionController:
    def __init__(self, library: RandomEmoteResolver,
                 on_change: Callable[[ExpressionSnapshot], None] | None = None) -> None:
        self._library = library
        self._lock = threading.Lock()
        self._listener = on_change
        emote_id, asset = library.choose(None)
        self._snapshot = ExpressionSnapshot(emote_id, asset)
        self._emit(self._snapshot)

    @property
    def snapshot(self) -> ExpressionSnapshot:
        with self._lock:
            return self._snapshot

    def set_listener(self, listener: Callable[[ExpressionSnapshot], None] | None) -> None:
        with self._lock:
            self._listener = listener

    def _emit(self, snapshot: ExpressionSnapshot) -> None:
        listener = self._listener
        if listener is not None:
            listener(snapshot)

    def advance(self) -> ExpressionSnapshot:
        with self._lock:
            emote_id, asset = self._library.choose(self._snapshot.emote_id)
            self._snapshot = ExpressionSnapshot(emote_id, asset)
            snapshot = self._snapshot
        self._emit(snapshot)
        return snapshot

    def trigger_meme(self, meme: ImageAsset) -> ExpressionSnapshot:
        snapshot = ExpressionSnapshot(self.snapshot.emote_id, self.snapshot.asset, meme)
        self._emit(snapshot)
        return snapshot
