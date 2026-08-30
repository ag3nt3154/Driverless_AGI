from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent.expression_assets import (
    ImageAsset,
    ProcessStateLibrary,
    RandomEmoteLibrary,
    TextFallback,
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


def test_random_emote_library_avoids_repeating_current_emote(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    _asset(root / "vad" / "calm.PNG")
    _asset(root / "vad" / "focused.jpg")
    library = RandomEmoteLibrary.load(root / "vad", root / "default.md")

    emote_id, asset = library.choose("calm")
    assert emote_id == "focused"
    assert asset == ImageAsset("focused", root / "vad" / "focused.jpg")


def test_random_emote_library_uses_injected_rng(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    _asset(root / "vad" / "calm.png")
    _asset(root / "vad" / "focused.png")
    rng = type("Rng", (), {"choice": staticmethod(lambda candidates: candidates[-1])})()
    library = RandomEmoteLibrary.load(root / "vad", root / "default.md", rng=rng)

    emote_id, asset = library.choose(None)

    assert emote_id == "focused"
    assert asset == ImageAsset("focused", root / "vad" / "focused.png")


def test_random_emote_library_ignores_manifest_and_unsupported_files(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    _asset(root / "vad" / "calm.png")
    _write(root / "vad" / "manifest.yaml", "coordinates: ignored\n")
    _write(root / "vad" / "notes.txt", "not an image")

    library = RandomEmoteLibrary.load(root / "vad", root / "default.md")

    assert library.choose(None) == (
        "calm",
        ImageAsset("calm", root / "vad" / "calm.png"),
    )


def test_random_emote_library_uses_fallback_when_no_images(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    _write(root / "vad" / "manifest.yaml", "coordinates: ignored\n")

    library = RandomEmoteLibrary.load(root / "vad", root / "default.md")

    emote_id, asset = library.choose(None)
    assert emote_id == "fallback"
    assert isinstance(asset, TextFallback)
    assert asset.text == "fallback"


def test_random_emote_library_warns_once_for_duplicate_stems(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    warnings: list[str] = []
    _write(root / "default.md", "fallback")
    _asset(root / "vad" / "calm.png")
    _asset(root / "vad" / "calm.jpg")

    RandomEmoteLibrary.load(root / "vad", root / "default.md", warnings.append)

    assert len(warnings) == 1
    assert "duplicate emote id ignored: calm" in warnings[0]


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


def test_load_fallback_uses_literal_dagi_when_default_is_invalid_utf8(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    fallback_path = root / "default.md"
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    fallback_path.write_bytes(b"\xff\xfe\xfa")

    fallback = load_fallback(root)

    assert fallback.path == fallback_path
    assert fallback.text == "DAGI"


def test_load_fallback_warns_when_default_is_unreadable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / ".dagi" / "emotes"
    unreadable = root / "default.md"
    unreadable.mkdir(parents=True)

    with caplog.at_level(logging.WARNING, logger="agent.expression_assets"):
        load_fallback(root)

    assert any(
        "fallback unreadable" in message and str(unreadable) in message
        for message in caplog.messages
    )
