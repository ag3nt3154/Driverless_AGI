from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from agent.base_tool import BaseTool

_SUPPORTED_SUFFIXES = frozenset({".gif", ".png", ".jpg", ".jpeg"})


def _scan_memes(memes_root: Path) -> dict[str, Path]:
    if not memes_root.is_dir():
        return {}
    return {
        p.stem: p
        for p in sorted(memes_root.iterdir())
        if p.is_file() and p.suffix.lower() in _SUPPORTED_SUFFIXES
    }


def _build_description(meme_stems: list[str]) -> str:
    base = (
        "Post a message to the message board with a meme and a text line."
    )
    if not meme_stems:
        return base + " No memes currently available."
    listing = ", ".join(meme_stems)
    return base + f" Available memes: {listing}."


class EmoteTool(BaseTool):
    name = "emote"

    def __init__(
        self,
        on_post: Callable[[str, str, str, str], None],
        memes_root: Path,
    ) -> None:
        self._on_post = on_post
        self._meme_map = _scan_memes(memes_root)
        self.description = _build_description(sorted(self._meme_map))

    @property
    def _parameters(self):
        return {
            "type": "object",
            "properties": {
                "meme": {
                    "type": "string",
                    "description": (
                        "Meme name (filename without extension) to display."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "What you want to say on the message board."
                    ),
                },
            },
            "required": ["meme", "text"],
        }

    def run(
        self,
        meme: str,
        text: str,
    ) -> str:
        path = self._meme_map.get(meme)
        if path is None:
            available = sorted(self._meme_map)
            raise ValueError(
                f"Meme {meme!r} not found. Available: {available}"
            )
        ts = datetime.now().isoformat(timespec="seconds")
        self._on_post("dagi", meme, str(path), text, ts)
        return f"Posted to message board: [{meme}] {text}"
