from __future__ import annotations

import time
from pathlib import Path


def format_elapsed(start: float | None) -> str:
    if start is None:
        return "0s"
    secs = int(time.monotonic() - start)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs // 3600}h {(secs % 3600) // 60:02d}m {secs % 60:02d}s"


def idle_emote_path(dagi_root: Path) -> Path | None:
    """The pet's idle process-state image for the empty chat, if configured."""
    from agent.expression_assets import ImageAsset, ProcessStateLibrary
    emotes = dagi_root / ".dagi" / "emotes"
    asset = ProcessStateLibrary.load(emotes / "states", emotes / "default.md").resolve("idle")
    return asset.path if isinstance(asset, ImageAsset) else None
