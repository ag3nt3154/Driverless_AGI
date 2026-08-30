from __future__ import annotations

import logging
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


def test_vad_library_random_selection_avoids_repeating_current_emote(
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

    emote_id, asset = library.resolve((0.0, 0.0, 0.0), "calm", 0.05)
    assert emote_id == "focused"
    assert asset == ImageAsset("focused", root / "vad" / "focused.jpg")


def test_vad_library_random_selection_ignores_vector(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    _asset(root / "vad" / "calm.png")
    _asset(root / "vad" / "focused.png")
    _write(
        root / "vad" / "manifest.yaml",
        (
            "version: 1\n"
            "emotes:\n"
            "  - id: calm\n"
            "    file: calm.png\n"
            "    vad: [0.0, 0.0, 0.0]\n"
            "  - id: focused\n"
            "    file: focused.png\n"
            "    vad: [1.0, 1.0, 1.0]\n"
        ),
    )
    monkeypatch.setattr(
        "agent.expression_assets.random.choice",
        lambda candidates: candidates[-1],
    )
    library = VadLibrary.load(root / "vad", root / "default.md")

    emote_id, asset = library.resolve((0.0, 0.0, 0.0), None, 0.05)

    assert emote_id == "focused"
    assert asset == ImageAsset("focused", root / "vad" / "focused.png")


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


def test_invalid_utf8_manifest_uses_default_text_fallback(tmp_path: Path) -> None:
    root = tmp_path / ".dagi" / "emotes"
    _write(root / "default.md", "fallback")
    manifest = root / "vad" / "manifest.yaml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_bytes(b"\xff\xfe\xfa")

    library = VadLibrary.load(root / "vad", root / "default.md")

    emote_id, asset = library.resolve((0.0, 0.0, 0.0), None, 0.05)
    assert emote_id == "fallback"
    assert isinstance(asset, TextFallback)
    assert asset.text == "fallback"


def test_random_vad_selection_skips_invalid_assets_and_warns_once(
    tmp_path: Path,
) -> None:
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
    second_id, second_asset = library.resolve((-1.0, -1.0, -1.0), None, 0.05)
    assert first_id == second_id == "calm"
    expected = ImageAsset("calm", root / "vad" / "calm.png")
    assert first_asset == second_asset == expected
    assert [warning for warning in warnings if "../outside.png" in warning] == [
        warnings[0]
    ]


def test_vad_library_ignores_invalid_current_asset_when_avoiding_repeats(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".dagi" / "emotes"
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
            "  - id: broken\n"
            "    file: ../outside.png\n"
            "    vad: [0.2, 0.0, 0.0]\n"
        ),
    )

    library = VadLibrary.load(root / "vad", root / "default.md")

    emote_id, asset = library.resolve((0.09, 0.0, 0.0), "broken", 0.05)
    assert emote_id == "calm"
    assert asset == ImageAsset("calm", root / "vad" / "calm.png")


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
        "default fallback unreadable" in message and str(unreadable) in message
        for message in caplog.messages
    )
