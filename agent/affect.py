from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Literal, Protocol

from agent.expression_assets import AssetRef, VadPoint

AffectReason = Literal["init", "adjust", "drift", "restore"]


class VadResolver(Protocol):
    def resolve(
        self,
        vector: VadPoint,
        current_id: str | None,
        hysteresis: float,
    ) -> tuple[str, AssetRef]: ...


def _finite(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _vector_payload(vector: "AffectVector") -> list[float]:
    return [vector.valence, vector.arousal, vector.dominance]


@dataclass(frozen=True)
class AffectConfig:
    drift_pull: float = 0.05
    drift_noise: float = 0.02
    emote_hysteresis: float = 0.05

    def __post_init__(self) -> None:
        pull = _finite("drift_pull", self.drift_pull)
        noise = _finite("drift_noise", self.drift_noise)
        hysteresis = _finite("emote_hysteresis", self.emote_hysteresis)
        if pull < 0:
            raise ValueError("drift_pull must be non-negative")
        if noise < 0:
            raise ValueError("drift_noise must be non-negative")
        if noise > 1:
            raise ValueError("drift_noise must be <= 1")
        if hysteresis < 0:
            raise ValueError("emote_hysteresis must be non-negative")
        object.__setattr__(self, "drift_pull", pull)
        object.__setattr__(self, "drift_noise", noise)
        object.__setattr__(self, "emote_hysteresis", hysteresis)


@dataclass(frozen=True)
class AffectVector:
    valence: float
    arousal: float
    dominance: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "valence", _finite("valence", self.valence))
        object.__setattr__(self, "arousal", _finite("arousal", self.arousal))
        object.__setattr__(self, "dominance", _finite("dominance", self.dominance))

    def as_tuple(self) -> VadPoint:
        return (self.valence, self.arousal, self.dominance)


@dataclass(frozen=True)
class AffectRestore:
    baseline: AffectVector
    current: AffectVector
    emote_id: str | None


@dataclass(frozen=True)
class AffectSnapshot:
    baseline: AffectVector
    current: AffectVector
    emote_id: str
    asset: AssetRef
    reason: AffectReason


class AffectController:
    def __init__(
        self,
        library: VadResolver,
        *,
        config: AffectConfig = AffectConfig(),
        baseline: AffectVector | None = None,
        current: AffectVector | None = None,
        current_emote_id: str | None = None,
        rng=None,
        record=None,
        on_change=None,
    ) -> None:
        self._library = library
        self._config = config
        self._rng = rng or random.Random()
        self._record = record or (lambda event, payload: None)
        self._on_change = on_change or (lambda snapshot: None)
        self._baseline = baseline or self._random_vector()
        initial_current = current or self._baseline
        self._current = self._baseline
        self._current_emote_id = current_emote_id
        self._snapshot: AffectSnapshot | None = None
        is_restore = current_emote_id is not None or (
            current is not None and current != self._baseline
        )
        self._apply_change(
            reason="restore" if is_restore else "init",
            current=initial_current,
            persist=not is_restore,
        )

    @property
    def baseline(self) -> AffectVector:
        return self._baseline

    @property
    def current(self) -> AffectVector:
        return self._current

    @property
    def current_emote_id(self) -> str:
        return self._snapshot.emote_id if self._snapshot is not None else ""

    @property
    def snapshot(self) -> AffectSnapshot:
        if self._snapshot is None:  # pragma: no cover - constructor always initializes it
            raise RuntimeError("AffectController is not initialized")
        return self._snapshot

    def set_listener(self, listener, *, emit_current: bool = True) -> None:
        self._on_change = listener
        if emit_current:
            self._on_change(self.snapshot)

    def adjust(self, delta: AffectVector) -> AffectSnapshot:
        return self._apply_delta(delta, "adjust")

    def drift(self) -> AffectSnapshot:
        delta = AffectVector(
            self._drift_axis(self._baseline.valence, self._current.valence),
            self._drift_axis(self._baseline.arousal, self._current.arousal),
            self._drift_axis(self._baseline.dominance, self._current.dominance),
        )
        return self._apply_delta(delta, "drift")

    def context_line(self) -> str:
        current = self._current
        return (
            f"Affect: V={current.valence:+.2f} A={current.arousal:+.2f} "
            f"D={current.dominance:+.2f} | emote={self.current_emote_id}"
        )

    def _apply_delta(self, delta: AffectVector, reason: Literal["adjust", "drift"]) -> AffectSnapshot:
        prior = self._current
        current = AffectVector(
            _clamp(prior.valence + delta.valence),
            _clamp(prior.arousal + delta.arousal),
            _clamp(prior.dominance + delta.dominance),
        )
        return self._apply_change(reason=reason, current=current, prior=prior, delta=delta)

    def _apply_change(
        self,
        *,
        reason: AffectReason,
        current: AffectVector,
        prior: AffectVector | None = None,
        delta: AffectVector | None = None,
        persist: bool = True,
    ) -> AffectSnapshot:
        emote_id, asset = self._library.resolve(
            current.as_tuple(),
            self._current_emote_id,
            self._config.emote_hysteresis,
        )
        self._current = current
        self._current_emote_id = emote_id
        snapshot = AffectSnapshot(
            baseline=self._baseline,
            current=current,
            emote_id=emote_id,
            asset=asset,
            reason=reason,
        )
        self._snapshot = snapshot
        if persist:
            event, payload = self._payload_for(reason, prior, delta, current, emote_id)
            self._record(event, payload)
        self._on_change(snapshot)
        return snapshot

    def _payload_for(
        self,
        reason: AffectReason,
        prior: AffectVector | None,
        delta: AffectVector | None,
        current: AffectVector,
        emote_id: str,
    ) -> tuple[str, dict[str, object]]:
        if reason == "init":
            return (
                "affect_init",
                {
                    "baseline": _vector_payload(self._baseline),
                    "current": _vector_payload(current),
                    "emote_id": emote_id,
                },
            )
        if prior is None or delta is None:
            raise ValueError(f"{reason} requires both prior and delta vectors")
        return (
            f"affect_{reason}",
            {
                "prior": _vector_payload(prior),
                "delta": _vector_payload(delta),
                "current": _vector_payload(current),
                "emote_id": emote_id,
            },
        )

    def _drift_axis(self, baseline: float, current: float) -> float:
        noise = self._rng.uniform(-self._config.drift_noise, self._config.drift_noise)
        return self._config.drift_pull * (baseline - current) + noise

    def _random_vector(self) -> AffectVector:
        return AffectVector(
            self._rng.uniform(-0.3, 0.3),
            self._rng.uniform(-0.3, 0.3),
            self._rng.uniform(-0.3, 0.3),
        )
