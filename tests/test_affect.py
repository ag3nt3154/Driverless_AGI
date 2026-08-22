from __future__ import annotations

import math
from pathlib import Path

import pytest

from agent.affect import (
    AffectConfig,
    AffectController,
    AffectRestore,
    AffectVector,
)
from agent.expression_assets import ImageAsset


class _FakeLibrary:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[float, float, float], str | None, float]] = []

    def resolve(
        self,
        vector: tuple[float, float, float],
        current_id: str | None,
        hysteresis: float,
    ) -> tuple[str, ImageAsset]:
        self.calls.append((vector, current_id, hysteresis))
        emote_id = (
            "energized"
            if vector[1] > 0.2
            else "tense"
            if vector[0] < -0.2
            else "steady"
        )
        return emote_id, ImageAsset(emote_id, Path(f"{emote_id}.png"))


class _StubRng:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self.calls: list[tuple[float, float]] = []

    def uniform(self, start: float, end: float) -> float:
        self.calls.append((start, end))
        return self._values.pop(0)


def test_affect_vector_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="valence must be finite"):
        AffectVector(math.inf, 0.0, 0.0)

    with pytest.raises(ValueError, match="arousal must be finite"):
        AffectVector(0.0, math.nan, 0.0)

    assert AffectVector(0.1, -0.2, 0.3).as_tuple() == (0.1, -0.2, 0.3)


def test_random_initialization_stays_in_range_and_records_init() -> None:
    library = _FakeLibrary()
    rng = _StubRng([0.25, -0.3, 0.15])
    records: list[tuple[str, dict[str, object]]] = []
    seen = []

    controller = AffectController(
        library,
        rng=rng,
        record=lambda event, payload: records.append((event, payload)),
        on_change=seen.append,
    )

    assert controller.baseline == AffectVector(0.25, -0.3, 0.15)
    assert controller.current == AffectVector(0.25, -0.3, 0.15)
    assert controller.current_emote_id == "steady"
    assert records == [
        (
            "affect_init",
            {
                "baseline": [0.25, -0.3, 0.15],
                "current": [0.25, -0.3, 0.15],
                "emote_id": "steady",
            },
        )
    ]
    assert seen[0].reason == "init"
    assert seen[0].asset == ImageAsset("steady", Path("steady.png"))
    assert library.calls == [((0.25, -0.3, 0.15), None, 0.05)]
    assert rng.calls == [(-0.3, 0.3), (-0.3, 0.3), (-0.3, 0.3)]


def test_adjust_clamps_each_axis_and_publishes_after_state_updates() -> None:
    library = _FakeLibrary()
    seen: list[tuple[AffectVector, AffectVector, str]] = []
    records: list[tuple[str, dict[str, object], AffectVector]] = []
    controller = AffectController(
        library,
        baseline=AffectVector(0.0, 0.0, 0.0),
        current=AffectVector(0.9, -0.9, 0.2),
        record=lambda event, payload: records.append((event, payload, controller.current)),
        on_change=lambda snapshot: seen.append(
            (snapshot.baseline, snapshot.current, snapshot.emote_id)
        ),
    )
    records.clear()
    seen.clear()

    snapshot = controller.adjust(AffectVector(0.5, -0.5, 0.9))

    assert snapshot.current == AffectVector(1.0, -1.0, 1.0)
    assert controller.current == AffectVector(1.0, -1.0, 1.0)
    assert controller.current_emote_id == "steady"
    assert records == [
        (
            "affect_adjust",
            {
                "prior": [0.9, -0.9, 0.2],
                "delta": [0.5, -0.5, 0.9],
                "current": [1.0, -1.0, 1.0],
                "emote_id": "steady",
            },
            AffectVector(1.0, -1.0, 1.0),
        )
    ]
    assert seen == [(AffectVector(0.0, 0.0, 0.0), AffectVector(1.0, -1.0, 1.0), "steady")]
    assert library.calls[-1] == ((1.0, -1.0, 1.0), "steady", 0.05)


def test_seeded_drift_pulls_toward_baseline() -> None:
    library = _FakeLibrary()
    rng = _StubRng([0.0, 0.0, 0.0])
    records: list[tuple[str, dict[str, object]]] = []
    controller = AffectController(
        library,
        baseline=AffectVector(0.0, 0.0, 0.0),
        current=AffectVector(1.0, -1.0, 0.5),
        rng=rng,
        record=lambda event, payload: records.append((event, payload)),
    )
    records.clear()

    snapshot = controller.drift()

    assert snapshot.current == AffectVector(0.95, -0.95, 0.475)
    assert records == [
        (
            "affect_drift",
            {
                "prior": [1.0, -1.0, 0.5],
                "delta": [-0.05, 0.05, -0.025],
                "current": [0.95, -0.95, 0.475],
                "emote_id": "steady",
            },
        )
    ]
    assert rng.calls == [(-0.02, 0.02), (-0.02, 0.02), (-0.02, 0.02)]


def test_set_listener_replaces_callback_and_can_emit_current_snapshot() -> None:
    library = _FakeLibrary()
    initial_events = []
    controller = AffectController(
        library,
        baseline=AffectVector(-0.3, 0.4, 0.0),
        current=AffectVector(-0.3, 0.4, 0.0),
        on_change=initial_events.append,
    )
    initial_events.clear()
    replacement_events = []

    controller.set_listener(replacement_events.append, emit_current=True)
    controller.adjust(AffectVector(0.0, 0.0, 0.0))

    assert initial_events == []
    assert [snapshot.reason for snapshot in replacement_events] == ["init", "adjust"]
    assert replacement_events[0].current == AffectVector(-0.3, 0.4, 0.0)
    assert replacement_events[1].current == AffectVector(-0.3, 0.4, 0.0)


def test_context_line_and_restore_seed_use_expected_shapes() -> None:
    library = _FakeLibrary()
    restore = AffectRestore(
        baseline=AffectVector(0.1, -0.2, 0.3),
        current=AffectVector(0.45, 0.0, -0.15),
        emote_id="steady",
    )

    controller = AffectController(
        library,
        baseline=restore.baseline,
        current=restore.current,
        current_emote_id=restore.emote_id,
    )

    assert controller.context_line() == "Affect: V=+0.45 A=+0.00 D=-0.15 | emote=steady"
