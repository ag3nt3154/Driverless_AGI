from __future__ import annotations

from pathlib import Path

from agent.affect import AffectController, AffectVector
from agent.expression_assets import ImageAsset
from tools.adjust_affect import AdjustAffectTool


class _FakeLibrary:
    def resolve(
        self,
        vector: tuple[float, float, float],
        current_id: str | None,
        hysteresis: float,
    ) -> tuple[str, ImageAsset]:
        emote_id = "bright" if vector[0] >= 0 else "steady"
        return emote_id, ImageAsset(emote_id, Path(f"{emote_id}.png"))


def test_schema_requires_three_bounded_deltas() -> None:
    tool = AdjustAffectTool(
        AffectController(
            _FakeLibrary(),
            baseline=AffectVector(0.0, 0.0, 0.0),
            current=AffectVector(0.0, 0.0, 0.0),
        )
    )

    schema = tool.schema()
    props = schema["function"]["parameters"]["properties"]

    assert schema["function"]["parameters"]["required"] == [
        "valence_delta",
        "arousal_delta",
        "dominance_delta",
    ]
    for key in ("valence_delta", "arousal_delta", "dominance_delta"):
        assert props[key]["type"] == "number"
        assert props[key]["minimum"] == -1
        assert props[key]["maximum"] == 1


def test_run_reports_prior_delta_result_and_selected_id() -> None:
    controller = AffectController(
        _FakeLibrary(),
        baseline=AffectVector(0.0, 0.0, 0.0),
        current=AffectVector(0.9, 0.1, 0.0),
    )
    tool = AdjustAffectTool(controller)

    result = tool.run(valence_delta=0.5, arousal_delta=-0.2, dominance_delta=0.3)

    assert "Prior: (0.9, 0.1, 0.0)" in result
    assert "Requested delta: (0.5, -0.2, 0.3)" in result
    assert "Result: (1.0, -0.1, 0.3)" in result
    assert "Selected ID: bright" in result
