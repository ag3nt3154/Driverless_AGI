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


def _reflect(value: float) -> float:
    """Reflect a value into [-1, +1] off the boundaries."""
    while value > 1.0 or value < -1.0:
        if value > 1.0:
            value = 2.0 - value
        if value < -1.0:
            value = -2.0 - value
    return value


def _bounded(name: str, value: float) -> float:
    value = _finite(name, value)
    if not -1.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between -1 and 1")
    return value


def _vector_payload(vector: "AffectVector") -> list[float]:
    return [vector.valence, vector.arousal, vector.dominance]


def _is_restore_seed(
    current_emote_id: str | None,
    current: "AffectVector | None",
    baseline: "AffectVector",
) -> bool:
    if current_emote_id is not None:
        return True
    return current is not None and current != baseline


@dataclass(frozen=True)
class AffectConfig:
    drift_pull: float = 0.05
    drift_noise: float = 0.02
    emote_hysteresis: float = 0.05
    wander_volatility: float = 0.08
    drift_interval: float = 1.0

    def __post_init__(self) -> None:
        pull = _finite("drift_pull", self.drift_pull)
        noise = _finite("drift_noise", self.drift_noise)
        hysteresis = _finite("emote_hysteresis", self.emote_hysteresis)
        wander = _finite("wander_volatility", self.wander_volatility)
        interval = _finite("drift_interval", self.drift_interval)
        if pull < 0:
            raise ValueError("drift_pull must be non-negative")
        if noise < 0:
            raise ValueError("drift_noise must be non-negative")
        if noise > 1:
            raise ValueError("drift_noise must be <= 1")
        if hysteresis < 0:
            raise ValueError("emote_hysteresis must be non-negative")
        if wander < 0:
            raise ValueError("wander_volatility must be non-negative")
        if interval < 0:
            raise ValueError("drift_interval must be non-negative")
        object.__setattr__(self, "drift_pull", pull)
        object.__setattr__(self, "drift_noise", noise)
        object.__setattr__(self, "emote_hysteresis", hysteresis)
        object.__setattr__(self, "wander_volatility", wander)
        object.__setattr__(self, "drift_interval", interval)


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
        import threading as _threading
        self._lock = _threading.Lock()
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
        is_restore = _is_restore_seed(current_emote_id, current, self._baseline)
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
        delta = AffectVector(
            _bounded("valence_delta", delta.valence),
            _bounded("arousal_delta", delta.arousal),
            _bounded("dominance_delta", delta.dominance),
        )
        with self._lock:
            return self._apply_delta(delta, "adjust")

    def drift(self) -> AffectSnapshot:
        with self._lock:
            snapshot = self.drift_without_notify()
        self.emit(snapshot)
        return snapshot

    def drift_without_notify(self) -> AffectSnapshot:
        self._wander_baseline()
        delta = AffectVector(
            self._drift_axis(self._baseline.valence, self._current.valence),
            self._drift_axis(self._baseline.arousal, self._current.arousal),
            self._drift_axis(self._baseline.dominance, self._current.dominance),
        )
        return self._apply_delta(delta, "drift", emit=False)

    def emit(self, snapshot: AffectSnapshot) -> None:
        self._on_change(snapshot)

    def context_line(self) -> str:
        current = self._current
        return (
            f"Affect: V={current.valence:+.2f} A={current.arousal:+.2f} "
            f"D={current.dominance:+.2f} | emote={self.current_emote_id}"
        )

    def _apply_delta(
        self,
        delta: AffectVector,
        reason: Literal["adjust", "drift"],
        *,
        emit: bool = True,
    ) -> AffectSnapshot:
        prior = self._current
        current = AffectVector(
            _clamp(prior.valence + delta.valence),
            _clamp(prior.arousal + delta.arousal),
            _clamp(prior.dominance + delta.dominance),
        )
        return self._apply_change(
            reason=reason,
            current=current,
            prior=prior,
            delta=delta,
            emit=emit,
        )

    def _apply_change(
        self,
        *,
        reason: AffectReason,
        current: AffectVector,
        prior: AffectVector | None = None,
        delta: AffectVector | None = None,
        persist: bool = True,
        emit: bool = True,
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
            event, payload = self._payload_for(reason, prior, delta, snapshot)
            self._record(event, payload)
        if emit:
            self.emit(snapshot)
        return snapshot

    def _payload_for(
        self,
        reason: AffectReason,
        prior: AffectVector | None,
        delta: AffectVector | None,
        snapshot: AffectSnapshot,
    ) -> tuple[str, dict[str, object]]:
        if reason == "init":
            return (
                "affect_init",
                {
                    "baseline": _vector_payload(self._baseline),
                    "current": _vector_payload(snapshot.current),
                    "emote_id": snapshot.emote_id,
                },
            )
        if prior is None or delta is None:
            raise ValueError(f"{reason} requires both prior and delta vectors")
        return (
            f"affect_{reason}",
            {
                "baseline": _vector_payload(self._baseline),
                "prior": _vector_payload(prior),
                "delta": _vector_payload(delta),
                "current": _vector_payload(snapshot.current),
                "emote_id": snapshot.emote_id,
            },
        )

    def _drift_axis(self, baseline: float, current: float) -> float:
        noise = self._rng.uniform(-self._config.drift_noise, self._config.drift_noise)
        return self._config.drift_pull * (baseline - current) + noise

    def _wander_baseline(self) -> None:
        sigma = self._config.wander_volatility
        if sigma <= 0:
            return
        self._baseline = AffectVector(
            _reflect(self._baseline.valence + self._rng.gauss(0, sigma)),
            _reflect(self._baseline.arousal + self._rng.gauss(0, sigma)),
            _reflect(self._baseline.dominance + self._rng.gauss(0, sigma)),
        )

    def _random_vector(self) -> AffectVector:
        return AffectVector(
            self._rng.uniform(-1.0, 1.0),
            self._rng.uniform(-1.0, 1.0),
            self._rng.uniform(-1.0, 1.0),
        )
