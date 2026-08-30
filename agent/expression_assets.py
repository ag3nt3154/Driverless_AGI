from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import yaml

_BUILTIN_FALLBACK = "DAGI"
_SUPPORTED_SUFFIXES = frozenset({".gif", ".png", ".jpg", ".jpeg"})
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageAsset:
    id: str
    path: Path


@dataclass(frozen=True)
class TextFallback:
    path: Path
    reason: str
    text: str


AssetRef: TypeAlias = ImageAsset | TextFallback


def _load_fallback(path: Path, reason: str, warn_once) -> TextFallback:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        warn_once(f"fallback:{path}", f"[expression_assets] fallback unreadable: {path} ({exc})")
        text = _BUILTIN_FALLBACK
    return TextFallback(path, reason, text)


def load_fallback(emotes_root: Path) -> TextFallback:
    return _load_fallback(emotes_root / "default.md", "default fallback",
                          lambda _key, message: _LOGGER.warning(message))


class RandomEmoteLibrary:
    def __init__(self, assets: tuple[ImageAsset, ...], fallback_path: Path, *,
                 disabled_reason: str | None = None, warn=None, rng=None) -> None:
        self._assets = assets
        self._fallback_path = fallback_path
        self._disabled_reason = disabled_reason
        self._warn = warn or _LOGGER.warning
        self._warned: set[str] = set()
        self._rng = rng or random

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self._warn(message)

    def _fallback(self, reason: str) -> TextFallback:
        return _load_fallback(self._fallback_path, reason, self._warn_once)

    @classmethod
    def load(cls, assets_root: Path, fallback_path: Path, warn=None, rng=None):
        library = cls((), fallback_path, warn=warn, rng=rng)
        try:
            paths = sorted(path for path in assets_root.iterdir()
                           if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES)
        except OSError as exc:
            library._disabled_reason = f"emote directory unavailable: {exc}"
            return library
        by_id: dict[str, ImageAsset] = {}
        for path in paths:
            if path.stem in by_id:
                library._warn_once(f"duplicate:{path.stem}",
                                   f"[expression_assets] duplicate emote id ignored: {path.stem}")
                continue
            by_id[path.stem] = ImageAsset(path.stem, path)
        library._assets = tuple(by_id.values())
        if not library._assets:
            library._disabled_reason = "no valid emote assets"
        return library

    def choose(self, current_id: str | None) -> tuple[str, AssetRef]:
        if not self._assets:
            return "fallback", self._fallback(self._disabled_reason or "no valid emote assets")
        candidates = tuple(asset for asset in self._assets if asset.id != current_id) or self._assets
        asset = self._rng.choice(candidates)
        return asset.id, asset


def _read_manifest(path: Path, channel: str, warn_once) -> dict | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        warn_once(f"{channel}:manifest:{path}", f"[expression_assets] {channel} manifest unreadable: {path} ({exc})")
        return None
    return data if isinstance(data, dict) else None


def _validate(path_root: Path, value: object, channel: str, key: str, warn_once) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = (path_root / value).resolve()
    try:
        path.relative_to(path_root.resolve())
    except ValueError:
        return None
    if path.suffix.lower() not in _SUPPORTED_SUFFIXES or not path.is_file():
        return None
    return path


class ProcessStateLibrary:
    def __init__(self, assets: dict[str, ImageAsset | None], fallback_path: Path, *,
                 disabled_reason: str | None = None, warn=None) -> None:
        self._assets = assets; self._fallback_path = fallback_path
        self._disabled_reason = disabled_reason; self._warn = warn or _LOGGER.warning
        self._warned: set[str] = set()

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key); self._warn(message)

    def _fallback(self, reason: str) -> TextFallback:
        return _load_fallback(self._fallback_path, reason, self._warn_once)

    @classmethod
    def load(cls, root: Path, fallback_path: Path, warn=None):
        lib = cls({}, fallback_path, warn=warn); manifest_path = root / "manifest.yaml"
        manifest = _read_manifest(manifest_path, "states", lib._warn_once)
        if not manifest or manifest.get("version") != 1:
            lib._disabled_reason = "states manifest unavailable"; return lib
        raw = manifest.get("states")
        if not isinstance(raw, dict) or any(k not in raw for k in ("idle", "thinking", "tool")):
            lib._disabled_reason = "states required keys"; return lib
        lib._assets = {k: (ImageAsset(k, p) if (p := _validate(root, v, "states", k, lib._warn_once)) else None)
                       for k, v in raw.items() if isinstance(k, str) and k}
        return lib

    def resolve(self, state: str) -> AssetRef:
        if self._disabled_reason:
            return self._fallback(self._disabled_reason)
        keys = [state, "tool", "thinking", "idle"] if state.startswith("tool:") else [state, "idle"]
        for key in keys:
            if key in self._assets:
                asset = self._assets[key]
                return asset if asset is not None else self._fallback(f"invalid process asset: {key}")
        return self._fallback(f"unknown process state: {state}")
