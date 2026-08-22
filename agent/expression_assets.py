from __future__ import annotations

import logging
import math
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
VadPoint: TypeAlias = tuple[float, float, float]


@dataclass(frozen=True)
class VadEntry:
    id: str
    point: VadPoint
    asset: ImageAsset | None


def _read_manifest(
    manifest_path: Path,
    channel: str,
    warn_once,
) -> dict[object, object] | None:
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        warn_once(
            f"{channel}:manifest:{manifest_path}",
            f"[expression_assets] {channel} manifest unreadable: {manifest_path} ({exc})",
        )
        return None
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        warn_once(
            f"{channel}:manifest:{manifest_path}",
            f"[expression_assets] {channel} manifest invalid YAML: {manifest_path} ({exc})",
        )
        return None
    if not isinstance(data, dict):
        warn_once(
            f"{channel}:manifest-shape:{manifest_path}",
            f"[expression_assets] {channel} manifest must be a mapping: {manifest_path}",
        )
        return None
    return data


def _validate_asset_path(
    assets_root: Path,
    relative_path: object,
    channel: str,
    asset_id: str,
    warn_once,
) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        warn_once(
            f"{channel}:asset:{asset_id}:path",
            f"[expression_assets] {channel} asset {asset_id!r} must define a non-empty file path",
        )
        return None
    candidate = (assets_root / relative_path).resolve()
    try:
        candidate.relative_to(assets_root.resolve())
    except ValueError:
        warn_once(
            f"{channel}:asset:{asset_id}:escape:{relative_path}",
            f"[expression_assets] {channel} asset {asset_id!r} escapes {assets_root}: {relative_path}",
        )
        return None
    if candidate.suffix.lower() not in _SUPPORTED_SUFFIXES:
        warn_once(
            f"{channel}:asset:{asset_id}:suffix:{candidate.suffix.lower()}",
            f"[expression_assets] {channel} asset {asset_id!r} has unsupported suffix: {candidate}",
        )
        return None
    if not candidate.is_file():
        warn_once(
            f"{channel}:asset:{asset_id}:missing:{candidate}",
            f"[expression_assets] {channel} asset {asset_id!r} is not a file: {candidate}",
        )
        return None
    return candidate


def _load_fallback(
    fallback_path: Path,
    reason: str,
    warn_once,
) -> TextFallback:
    try:
        text = fallback_path.read_text(encoding="utf-8")
    except OSError as exc:
        warn_once(
            f"fallback:{fallback_path}",
            f"[expression_assets] default fallback unreadable: {fallback_path} ({exc})",
        )
        text = _BUILTIN_FALLBACK
    return TextFallback(path=fallback_path, reason=reason, text=text)


def _coerce_vad_point(raw_point: object, asset_id: str, manifest_path: Path) -> VadPoint:
    if not isinstance(raw_point, list) or len(raw_point) != 3:
        raise ValueError(
            f"VAD asset {asset_id!r} in {manifest_path} must define exactly three coordinates"
        )
    values = []
    for axis, raw_value in zip(("valence", "arousal", "dominance"), raw_point):
        if not isinstance(raw_value, int | float):
            raise ValueError(f"VAD asset {asset_id!r} has non-numeric {axis}: {raw_value!r}")
        value = float(raw_value)
        if not math.isfinite(value) or not -1.0 <= value <= 1.0:
            raise ValueError(
                f"VAD asset {asset_id!r} has out-of-range {axis}: {raw_value!r}"
            )
        values.append(value)
    return (values[0], values[1], values[2])


def _distance(left: VadPoint, right: VadPoint) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def load_fallback(emotes_root: Path) -> TextFallback:
    fallback_path = emotes_root / "default.md"
    return _load_fallback(fallback_path, "default fallback", lambda *_args: None)


class VadLibrary:
    def __init__(
        self,
        entries: tuple[VadEntry, ...],
        fallback_path: Path,
        *,
        disabled_reason: str | None = None,
        warn=None,
    ) -> None:
        self._entries = entries
        self._fallback_path = fallback_path
        self._disabled_reason = disabled_reason
        self._warn = warn or _LOGGER.warning
        self._warned: set[str] = set()
        self._by_id = {entry.id: entry for entry in entries}

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self._warn(message)

    def _fallback(self, reason: str) -> TextFallback:
        return _load_fallback(self._fallback_path, reason, self._warn_once)

    @classmethod
    def load(cls, assets_root: Path, fallback_path: Path, warn=None) -> VadLibrary:
        library = cls((), fallback_path, warn=warn)
        manifest_path = assets_root / "manifest.yaml"
        manifest = _read_manifest(manifest_path, "vad", library._warn_once)
        if manifest is None:
            library._disabled_reason = "vad manifest unavailable"
            return library
        if manifest.get("version") != 1:
            library._warn_once(
                f"vad:version:{manifest_path}",
                f"[expression_assets] vad manifest must declare version 1: {manifest_path}",
            )
            library._disabled_reason = "vad manifest version"
            return library
        raw_entries = manifest.get("emotes")
        if not isinstance(raw_entries, list) or not raw_entries:
            library._warn_once(
                f"vad:entries:{manifest_path}",
                f"[expression_assets] vad manifest must define a non-empty emotes list: {manifest_path}",
            )
            library._disabled_reason = "vad manifest entries"
            return library
        seen_ids: set[str] = set()
        entries: list[VadEntry] = []
        try:
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, dict):
                    raise ValueError(f"VAD entries in {manifest_path} must be mappings")
                asset_id = raw_entry.get("id")
                if not isinstance(asset_id, str) or not asset_id.strip():
                    raise ValueError(f"VAD entries in {manifest_path} must define a non-empty id")
                if asset_id in seen_ids:
                    raise ValueError(f"Duplicate VAD id {asset_id!r} in {manifest_path}")
                seen_ids.add(asset_id)
                point = _coerce_vad_point(raw_entry.get("vad"), asset_id, manifest_path)
                asset_path = _validate_asset_path(
                    assets_root,
                    raw_entry.get("file"),
                    "vad",
                    asset_id,
                    library._warn_once,
                )
                asset = ImageAsset(asset_id, asset_path) if asset_path else None
                entries.append(VadEntry(asset_id, point, asset))
        except ValueError as exc:
            library._warn_once(
                f"vad:invalid:{manifest_path}",
                f"[expression_assets] {exc}",
            )
            library._disabled_reason = str(exc)
            return library
        library._entries = tuple(entries)
        library._by_id = {entry.id: entry for entry in library._entries}
        return library

    def resolve(
        self,
        vector: VadPoint,
        current_id: str | None,
        hysteresis: float,
    ) -> tuple[str, AssetRef]:
        if self._disabled_reason or not self._entries:
            return "fallback", self._fallback(self._disabled_reason or "vad library unavailable")
        nearest = min(self._entries, key=lambda entry: _distance(vector, entry.point))
        current = self._by_id.get(current_id) if current_id else None
        if current and current.asset is not None and current.id != nearest.id:
            current_distance = _distance(vector, current.point)
            challenger_distance = _distance(vector, nearest.point)
            if current_distance - challenger_distance < hysteresis:
                nearest = current
        if nearest.asset is None:
            return nearest.id, self._fallback(f"invalid VAD asset: {nearest.id}")
        return nearest.id, nearest.asset


class ProcessStateLibrary:
    def __init__(
        self,
        assets: dict[str, ImageAsset | None],
        fallback_path: Path,
        *,
        disabled_reason: str | None = None,
        warn=None,
    ) -> None:
        self._assets = assets
        self._fallback_path = fallback_path
        self._disabled_reason = disabled_reason
        self._warn = warn or _LOGGER.warning
        self._warned: set[str] = set()

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self._warn(message)

    def _fallback(self, reason: str) -> TextFallback:
        return _load_fallback(self._fallback_path, reason, self._warn_once)

    @classmethod
    def load(
        cls,
        assets_root: Path,
        fallback_path: Path,
        warn=None,
    ) -> ProcessStateLibrary:
        library = cls({}, fallback_path, warn=warn)
        manifest_path = assets_root / "manifest.yaml"
        manifest = _read_manifest(manifest_path, "states", library._warn_once)
        if manifest is None:
            library._disabled_reason = "states manifest unavailable"
            return library
        if manifest.get("version") != 1:
            library._warn_once(
                f"states:version:{manifest_path}",
                f"[expression_assets] states manifest must declare version 1: {manifest_path}",
            )
            library._disabled_reason = "states manifest version"
            return library
        raw_states = manifest.get("states")
        if not isinstance(raw_states, dict):
            library._warn_once(
                f"states:shape:{manifest_path}",
                f"[expression_assets] states manifest must define a states mapping: {manifest_path}",
            )
            library._disabled_reason = "states manifest mapping"
            return library
        missing = [key for key in ("idle", "thinking", "tool") if key not in raw_states]
        if missing:
            library._warn_once(
                f"states:required:{manifest_path}",
                f"[expression_assets] states manifest missing required keys {missing}: {manifest_path}",
            )
            library._disabled_reason = "states required keys"
            return library
        assets: dict[str, ImageAsset | None] = {}
        for state, raw_path in raw_states.items():
            if not isinstance(state, str) or not state:
                library._warn_once(
                    f"states:key:{manifest_path}",
                    f"[expression_assets] states manifest contains an invalid key: {state!r}",
                )
                library._disabled_reason = "states invalid key"
                return library
            asset_path = _validate_asset_path(
                assets_root,
                raw_path,
                "states",
                state,
                library._warn_once,
            )
            assets[state] = ImageAsset(state, asset_path) if asset_path else None
        library._assets = assets
        return library

    def resolve(self, state: str) -> AssetRef:
        if self._disabled_reason:
            return self._fallback(self._disabled_reason)
        keys = [state, "thinking", "idle"] if state == "tool" else [state, "idle"]
        if state.startswith("tool:"):
            keys = [state, "tool", "thinking", "idle"]
        for key in keys:
            if key not in self._assets:
                continue
            asset = self._assets[key]
            if asset is None:
                return self._fallback(f"invalid process asset: {key}")
            return asset
        return self._fallback(f"unknown process state: {state}")
