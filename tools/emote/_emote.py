from __future__ import annotations

from pathlib import Path

from agent.affect import AffectController, AffectVector
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
    base = (
        "Express emotion via VAD adjustment and/or meme display. "
        "At least one of vad_delta or meme must be provided."
    )
    if not meme_stems:
        return base + " No memes currently available."
    listing = ", ".join(meme_stems)
    return base + f" Available memes: {listing}."


class EmoteTool(BaseTool):
    name = "emote"

    def __init__(
        self,
        controller: AffectController,
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
                "vad_delta": {
                    "type": "object",
                    "description": "Relative VAD adjustment.",
                    "properties": {
                        "valence_delta": {
                            "type": "number",
                            "minimum": -1,
                            "maximum": 1,
                            "description": "Relative change to valence. Use 0 to keep unchanged.",
                        },
                        "arousal_delta": {
                            "type": "number",
                            "minimum": -1,
                            "maximum": 1,
                            "description": "Relative change to arousal. Use 0 to keep unchanged.",
                        },
                        "dominance_delta": {
                            "type": "number",
                            "minimum": -1,
                            "maximum": 1,
                            "description": "Relative change to dominance. Use 0 to keep unchanged.",
                        },
                    },
                    "required": ["valence_delta", "arousal_delta", "dominance_delta"],
                },
                "meme": {
                    "type": "string",
                    "description": (
                        "Meme name (filename without extension) to display for 2 cycles."
                    ),
                },
            },
        }

    def run(
        self,
        vad_delta: dict | None = None,
        meme: str | None = None,
    ) -> str:
        if vad_delta is None and meme is None:
            raise ValueError("At least one of vad_delta or meme must be provided.")
        parts: list[str] = []
        if vad_delta is not None:
            parts.append(self._apply_vad(vad_delta))
        if meme is not None:
            parts.append(self._apply_meme(meme))
        return "\n".join(parts)

    def _apply_vad(self, vad_delta: dict) -> str:
        before = self._controller.current.as_tuple()
        delta = AffectVector(
            vad_delta["valence_delta"],
            vad_delta["arousal_delta"],
            vad_delta["dominance_delta"],
        )
        snapshot = self._controller.adjust(delta)
        return (
            f"Prior: {before}\n"
            f"Requested delta: {delta.as_tuple()}\n"
            f"Result: {snapshot.current.as_tuple()}\n"
            f"Selected ID: {snapshot.emote_id}"
        )

    def _apply_meme(self, meme_name: str) -> str:
        path = self._meme_map.get(meme_name)
        if path is None:
            available = sorted(self._meme_map)
            raise ValueError(
                f"Meme {meme_name!r} not found. Available: {available}"
            )
        asset = ImageAsset(meme_name, path)
        self._controller.trigger_meme(asset)
        return f"Meme triggered: {meme_name}"
