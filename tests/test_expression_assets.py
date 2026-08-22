from __future__ import annotations

import math
from pathlib import Path

import pytest

from agent.expression_assets import (
    ImageAsset,
    ProcessStateLibrary,
    TextFallback,
    VadLibrary,
    load_fallback,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _asset(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture")
    return path


def test_vad_library_selects_nearest_entry_and_keeps_current_with_hysteresis(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    _asset(root / "vad" / "calm.PNG")
    _asset(root / "vad" / "focused.jpg")
    _write(
        root / "vad" / "manifest.yaml",
        (
            "version: 1\n"
            "emotes:\n"
            "  - id: calm\n"
            "    file: calm.PNG\n"
            "    vad: [0.0, 0.0, 0.0]\n"
            "  - id: focused\n"
            "    file: focused.jpg\n"
            "    vad: [0.2, 0.0, 0.0]\n"
        ),
    )

    library = VadLibrary.load(root / "vad", root / "default.md")

    emote_id, asset = library.resolve((0.11, 0.0, 0.0), "calm", 0.05)
    assert emote_id == "calm"
    assert asset == ImageAsset("calm", root / "vad" / "calm.PNG")

    emote_id, asset = library.resolve((0.11, 0.0, 0.0), "calm", 0.01)
    assert emote_id == "focused"
    assert asset == ImageAsset("focused", root / "vad" / "focused.jpg")


@pytest.mark.parametrize(
    ("manifest_text", "vector"),
    [
        (
            (
                "version: 1\n"
                "emotes:\n"
                "  - id: dup\n"
                "    file: one.png\n"
                "    vad: [0.0, 0.0, 0.0]\n"
                "  - id: dup\n"
                "    file: two.png\n"
                "    vad: [0.1, 0.0, 0.0]\n"
            ),
            (0.0, 0.0, 0.0),
        ),
        (
            (
                "version: 2\n"
                "emotes:\n"
                "  - id: calm\n"
                "    file: calm.png\n"
                "    vad: [0.0, 0.0, 0.0]\n"
            ),
            (0.0, 0.0, 0.0),
        ),
        (
            (
                "version: 1\n"
                "emotes:\n"
                "  - id: bad\n"
                "    file: calm.png\n"
                f"    vad: [{math.inf}, 0.0, 0.0]\n"
            ),
            (0.0, 0.0, 0.0),
        ),
        (
            (
                "version: 1\n"
                "emotes:\n"
                "  - id: bad\n"
                "    file: calm.png\n"
                "    vad: [2.0, 0.0, 0.0]\n"
            ),
            (0.0, 0.0, 0.0),
        ),
    ],
)
def test_bad_vad_manifest_disables_only_that_library(
    tmp_path: Path, manifest_text: str, vector: tuple[float, float, float]
) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    _asset(root / "vad" / "one.png")
    _asset(root / "vad" / "two.png")
    _asset(root / "vad" / "calm.png")
    _write(root / "vad" / "manifest.yaml", manifest_text)

    library = VadLibrary.load(root / "vad", root / "default.md")

    emote_id, asset = library.resolve(vector, None, 0.05)
    assert emote_id == "fallback"
    assert isinstance(asset, TextFallback)
    assert asset.text == "fallback"


def test_invalid_selected_vad_asset_falls_back_and_warns_once(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    warnings: list[str] = []
    _write(root / "default.md", "fallback")
    _asset(root / "vad" / "calm.png")
    _write(
        root / "vad" / "manifest.yaml",
        (
            "version: 1\n"
            "emotes:\n"
            "  - id: calm\n"
            "    file: calm.png\n"
            "    vad: [0.0, 0.0, 0.0]\n"
            "  - id: escaped\n"
            "    file: ../outside.png\n"
            "    vad: [1.0, 1.0, 1.0]\n"
        ),
    )

    library = VadLibrary.load(root / "vad", root / "default.md", warnings.append)

    emote_id, asset = library.resolve((0.0, 0.0, 0.0), None, 0.05)
    assert emote_id == "calm"
    assert asset == ImageAsset("calm", root / "vad" / "calm.png")

    first_id, first_asset = library.resolve((1.0, 1.0, 1.0), None, 0.05)
    second_id, second_asset = library.resolve((1.0, 1.0, 1.0), None, 0.05)
    assert first_id == second_id == "escaped"
    assert isinstance(first_asset, TextFallback)
    assert isinstance(second_asset, TextFallback)
    assert [warning for warning in warnings if "../outside.png" in warning] == [
        warnings[-1]
    ]


def test_process_state_requires_fallback_keys(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    _asset(root / "states" / "idle.gif")
    _asset(root / "states" / "thinking.gif")
    _write(
        root / "states" / "manifest.yaml",
        "version: 1\nstates:\n  idle: idle.gif\n  thinking: thinking.gif\n",
    )

    library = ProcessStateLibrary.load(root / "states", root / "default.md")

    asset = library.resolve("thinking")
    assert isinstance(asset, TextFallback)
    assert asset.text == "fallback"


def test_process_state_uses_exact_fallback_chain(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    _asset(root / "states" / "idle.gif")
    _asset(root / "states" / "thinking.gif")
    _asset(root / "states" / "working.gif")
    _asset(root / "states" / "reading.gif")
    _write(
        root / "states" / "manifest.yaml",
        (
            "version: 1\n"
            "states:\n"
            "  idle: idle.gif\n"
            "  thinking: thinking.gif\n"
            "  tool: working.gif\n"
            "  \"tool:read\": reading.gif\n"
        ),
    )

    library = ProcessStateLibrary.load(root / "states", root / "default.md")

    assert library.resolve("tool:read") == ImageAsset(
        "tool:read", root / "states" / "reading.gif"
    )
    assert library.resolve("tool:grep") == ImageAsset("tool", root / "states" / "working.gif")
    assert library.resolve("unknown") == ImageAsset("idle", root / "states" / "idle.gif")


def test_process_state_invalid_selected_asset_falls_back_without_disabling_library(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    _asset(root / "states" / "idle.gif")
    _asset(root / "states" / "thinking.gif")
    _asset(root / "states" / "working.gif")
    _write(
        root / "states" / "manifest.yaml",
        (
            "version: 1\n"
            "states:\n"
            "  idle: idle.gif\n"
            "  thinking: thinking.gif\n"
            "  tool: working.gif\n"
            "  \"tool:read\": ../escape.gif\n"
        ),
    )

    library = ProcessStateLibrary.load(root / "states", root / "default.md")

    assert isinstance(library.resolve("tool:read"), TextFallback)
    assert library.resolve("tool:grep") == ImageAsset("tool", root / "states" / "working.gif")


def test_load_fallback_preserves_unicode_whitespace(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    expected = "\u00a0keep\tthis\n\u3000exactly\n"
    _write(root / "default.md", expected)

    fallback = load_fallback(root)

    assert fallback.text == expected
    assert fallback.path == root / "default.md"


def test_load_fallback_uses_literal_dagi_when_default_is_unreadable(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    unreadable = root / "default.md"
    unreadable.mkdir(parents=True)

    fallback = load_fallback(root)

    assert fallback.path == unreadable
    assert fallback.text == "DAGI"
