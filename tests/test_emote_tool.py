from __future__ import annotations

from pathlib import Path

import pytest

from agent.expression_assets import ImageAsset
from tools.emote import EmoteTool


class _RecordingController:
    def __init__(self) -> None:
        self.memes: list[ImageAsset] = []

    def trigger_meme(self, asset: ImageAsset) -> None:
        self.memes.append(asset)


@pytest.fixture()
def memes_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "memes"
    directory.mkdir()
    (directory / "absolute_cinema.gif").write_bytes(b"GIF89a")
    (directory / "eat_first.png").write_bytes(b"\x89PNG")
    (directory / "notes.txt").write_text("ignored", encoding="utf-8")
    return directory


def test_schema_requires_only_meme(memes_dir: Path) -> None:
    tool = EmoteTool(_RecordingController(), memes_dir)

    parameters = tool.schema()["function"]["parameters"]

    assert set(parameters["properties"]) == {"meme"}
    assert parameters["required"] == ["meme"]


def test_meme_triggers_selected_asset(memes_dir: Path) -> None:
    controller = _RecordingController()
    tool = EmoteTool(controller, memes_dir)

    result = tool.run(meme="absolute_cinema")

    assert result == "Meme triggered: absolute_cinema"
    assert controller.memes == [
        ImageAsset("absolute_cinema", memes_dir / "absolute_cinema.gif")
    ]


def test_invalid_meme_name_raises(memes_dir: Path) -> None:
    tool = EmoteTool(_RecordingController(), memes_dir)

    with pytest.raises(ValueError, match="not found"):
        tool.run(meme="nonexistent")


def test_description_lists_only_supported_memes(memes_dir: Path) -> None:
    tool = EmoteTool(_RecordingController(), memes_dir)

    assert "absolute_cinema" in tool.description
    assert "eat_first" in tool.description
    assert "notes" not in tool.description


def test_empty_memes_dir_reports_no_memes(tmp_path: Path) -> None:
    empty = tmp_path / "memes"
    empty.mkdir()

    tool = EmoteTool(_RecordingController(), empty)

    assert "no memes" in tool.description.lower()
