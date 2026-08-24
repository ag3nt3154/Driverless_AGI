from __future__ import annotations

from pathlib import Path

import pytest

from agent.affect import AffectController, AffectVector
from agent.expression_assets import ImageAsset
from tools.emote import EmoteTool


class _FakeLibrary:
    def resolve(
        self,
        vector: tuple[float, float, float],
        current_id: str | None,
        hysteresis: float,
    ) -> tuple[str, ImageAsset]:
        emote_id = "bright" if vector[0] >= 0 else "steady"
        return emote_id, ImageAsset(emote_id, Path(f"{emote_id}.png"))


def _controller(**kw):
    defaults = dict(
        baseline=AffectVector(0.0, 0.0, 0.0),
        current=AffectVector(0.0, 0.0, 0.0),
    )
    defaults.update(kw)
    return AffectController(_FakeLibrary(), **defaults)


@pytest.fixture()
def memes_dir(tmp_path):
    d = tmp_path / "memes"
    d.mkdir()
    (d / "absolute_cinema.gif").write_bytes(b"GIF89a")
    (d / "eat_first.png").write_bytes(b"\x89PNG")
    return d


def test_schema_has_optional_vad_delta_and_meme(memes_dir):
    tool = EmoteTool(_controller(), memes_dir)
    schema = tool.schema()
    props = schema["function"]["parameters"]["properties"]
    assert "vad_delta" in props
    assert "meme" in props
    required = schema["function"]["parameters"].get("required") or []
    assert "vad_delta" not in required
    assert "meme" not in required


def test_vad_delta_only(memes_dir):
    ctrl = _controller(current=AffectVector(0.5, 0.0, 0.0))
    tool = EmoteTool(ctrl, memes_dir)
    result = tool.run(vad_delta={"valence_delta": 0.1, "arousal_delta": 0.0, "dominance_delta": 0.0})
    assert "Prior:" in result
    assert "Result:" in result


def test_meme_only(memes_dir):
    ctrl = _controller()
    tool = EmoteTool(ctrl, memes_dir)
    result = tool.run(meme="absolute_cinema")
    assert "absolute_cinema" in result


def test_both_vad_and_meme(memes_dir):
    ctrl = _controller()
    tool = EmoteTool(ctrl, memes_dir)
    result = tool.run(
        vad_delta={"valence_delta": 0.2, "arousal_delta": 0.0, "dominance_delta": 0.0},
        meme="eat_first",
    )
    assert "Prior:" in result
    assert "eat_first" in result


def test_neither_param_raises(memes_dir):
    tool = EmoteTool(_controller(), memes_dir)
    with pytest.raises(ValueError, match="at least one"):
        tool.run()


def test_invalid_meme_name_raises(memes_dir):
    tool = EmoteTool(_controller(), memes_dir)
    with pytest.raises(ValueError, match="not found"):
        tool.run(meme="nonexistent")


def test_description_lists_available_memes(memes_dir):
    tool = EmoteTool(_controller(), memes_dir)
    assert "absolute_cinema" in tool.description
    assert "eat_first" in tool.description


def test_empty_memes_dir(tmp_path):
    empty = tmp_path / "memes"
    empty.mkdir()
    tool = EmoteTool(_controller(), empty)
    assert "no memes" in tool.description.lower()


def test_schema_requires_three_bounded_deltas(memes_dir):
    tool = EmoteTool(_controller(), memes_dir)
    schema = tool.schema()
    vad_props = schema["function"]["parameters"]["properties"]["vad_delta"]["properties"]
    for key in ("valence_delta", "arousal_delta", "dominance_delta"):
        assert vad_props[key]["type"] == "number"
        assert vad_props[key]["minimum"] == -1
        assert vad_props[key]["maximum"] == 1


def test_run_reports_prior_delta_result_and_selected_id(memes_dir):
    controller = _controller(current=AffectVector(0.9, 0.1, 0.0))
    tool = EmoteTool(controller, memes_dir)
    result = tool.run(vad_delta={"valence_delta": 0.5, "arousal_delta": -0.2, "dominance_delta": 0.3})
    assert "Prior: (0.9, 0.1, 0.0)" in result
    assert "Requested delta: (0.5, -0.2, 0.3)" in result
    assert "Result: (1.0, -0.1, 0.3)" in result
    assert "Selected ID: bright" in result


@pytest.mark.parametrize(
    ("kwargs", "axis"),
    [
        (
            {"vad_delta": {"valence_delta": 1.01, "arousal_delta": 0.0, "dominance_delta": 0.0}},
            "valence",
        ),
        (
            {"vad_delta": {"valence_delta": 0.0, "arousal_delta": float("inf"), "dominance_delta": 0.0}},
            "arousal",
        ),
        (
            {"vad_delta": {"valence_delta": 0.0, "arousal_delta": 0.0, "dominance_delta": -1.01}},
            "dominance",
        ),
    ],
)
def test_run_rejects_invalid_vad_deltas(memes_dir, kwargs, axis):
    controller = _controller(current=AffectVector(0.25, 0.25, 0.25))
    tool = EmoteTool(controller, memes_dir)
    with pytest.raises(ValueError, match=axis):
        tool.run(**kwargs)
    assert controller.current == AffectVector(0.25, 0.25, 0.25)
