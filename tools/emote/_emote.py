from __future__ import annotations

from pathlib import Path

from agent.base_tool import BaseTool
from agent.expression_assets import ImageAsset

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
    base = "Display one available meme for two expression cycles."
    if not meme_stems:
        return base + " No memes currently available."
    listing = ", ".join(meme_stems)
    return base + f" Available memes: {listing}."


class EmoteTool(BaseTool):
    name = "emote"

    def __init__(
        self,
        controller,
        memes_root: Path,
    ) -> None:
        self._controller = controller
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
                        "Meme name (filename without extension) to display for 2 cycles."
                    ),
                },
            },
            "required": ["meme"],
        }

    def run(
        self,
        meme: str,
    ) -> str:
        path = self._meme_map.get(meme)
        if path is None:
            available = sorted(self._meme_map)
            raise ValueError(
                f"Meme {meme!r} not found. Available: {available}"
            )
        asset = ImageAsset(meme, path)
        self._controller.trigger_meme(asset)
        return f"Meme triggered: {meme}"
