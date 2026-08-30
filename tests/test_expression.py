from __future__ import annotations

from pathlib import Path

import pytest

from agent.expression import ExpressionConfig, ExpressionController
from agent.expression_assets import ImageAsset


class _Library:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def choose(self, current_id: str | None):
        self.calls.append(current_id)
        next_id = "two" if current_id == "one" else "one"
        return next_id, ImageAsset(next_id, Path(f"{next_id}.gif"))


def test_advance_selects_from_current_id_and_publishes() -> None:
    seen = []
    library = _Library()
    controller = ExpressionController(library, on_change=seen.append)

    snapshot = controller.advance()

    assert library.calls == [None, "one"]
    assert snapshot.emote_id == "two"
    assert seen[-1] == snapshot


def test_trigger_meme_preserves_random_asset_and_publishes(tmp_path: Path) -> None:
    seen = []
    controller = ExpressionController(_Library(), on_change=seen.append)
    original = controller.snapshot.asset
    meme = ImageAsset("cinema", tmp_path / "cinema.gif")

    snapshot = controller.trigger_meme(meme)

    assert snapshot.asset == original
    assert snapshot.meme_asset == meme
    assert seen[-1] == snapshot


@pytest.mark.parametrize("interval", [-1.0, float("inf"), float("nan")])
def test_expression_config_rejects_invalid_interval(interval: float) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        ExpressionConfig(interval)
