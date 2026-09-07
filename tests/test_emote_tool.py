from __future__ import annotations

from pathlib import Path

import pytest

from tools.emote import EmoteTool


@pytest.fixture()
def memes_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "memes"
    directory.mkdir()
    (directory / "absolute_cinema.gif").write_bytes(b"GIF89a")
    (directory / "eat_first.png").write_bytes(b"\x89PNG")
    (directory / "notes.txt").write_text("ignored", encoding="utf-8")
    return directory


class _PostRecorder:
    def __init__(self) -> None:
        self.posts: list[tuple[str, str, str, str, str]] = []

    def __call__(self, author, meme, path, text, ts) -> None:
        self.posts.append((author, meme, path, text, ts))


def test_schema_requires_meme_and_text(memes_dir: Path) -> None:
    tool = EmoteTool(on_post=_PostRecorder(), memes_root=memes_dir)

    parameters = tool.schema()["function"]["parameters"]

    assert set(parameters["properties"]) == {"meme", "text"}
    assert set(parameters["required"]) == {"meme", "text"}


def test_meme_triggers_post(memes_dir: Path) -> None:
    recorder = _PostRecorder()
    tool = EmoteTool(on_post=recorder, memes_root=memes_dir)

    result = tool.run(meme="absolute_cinema", text="wow")

    assert "absolute_cinema" in result
    assert "wow" in result
    assert len(recorder.posts) == 1
    author, meme, path, text, ts = recorder.posts[0]
    assert author == "dagi"
    assert meme == "absolute_cinema"
    assert text == "wow"


def test_invalid_meme_name_raises(memes_dir: Path) -> None:
    tool = EmoteTool(on_post=_PostRecorder(), memes_root=memes_dir)

    with pytest.raises(ValueError, match="not found"):
        tool.run(meme="nonexistent", text="hello")


def test_description_lists_only_supported_memes(memes_dir: Path) -> None:
    tool = EmoteTool(on_post=_PostRecorder(), memes_root=memes_dir)

    assert "absolute_cinema" in tool.description
    assert "eat_first" in tool.description
    assert "notes" not in tool.description


def test_empty_memes_dir_reports_no_memes(tmp_path: Path) -> None:
    empty = tmp_path / "memes"
    empty.mkdir()

    tool = EmoteTool(on_post=_PostRecorder(), memes_root=empty)

    assert "no memes" in tool.description.lower()
