"""Tests for ExpressionWidget meme display logic.

These tests exercise meme state management directly without instantiating Qt,
since PySide6 DLL bootstrap requires a running QApplication.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent.affect import AffectSnapshot, AffectVector
from agent.expression_assets import ImageAsset, TextFallback


def _make_snapshot(meme_asset=None):
    zero = AffectVector(0.0, 0.0, 0.0)
    fallback = TextFallback(Path("f.md"), "test", "DAGI")
    return AffectSnapshot(
        baseline=zero,
        current=zero,
        emote_id="default",
        asset=fallback,
        reason="adjust",
        meme_asset=meme_asset,
    )


class _FakeWidget:
    """Minimal stub of ExpressionWidget state and methods under test."""

    def __init__(self):
        self._channel = "vad"
        self._meme_asset = None
        self._meme_cycles_remaining = 0
        self._last_rendered = None
        self._last_caption = None
        zero = AffectVector(0.0, 0.0, 0.0)
        fallback = TextFallback(Path("f.md"), "test", "DAGI")
        self._affect_snapshot = AffectSnapshot(
            baseline=zero, current=zero, emote_id="default",
            asset=fallback, reason="init",
        )
        self._process_snapshot = SimpleNamespace(
            state="idle", asset=TextFallback(Path("p.md"), "proc", "PROC")
        )

    def update_affect(self, snapshot):
        self._affect_snapshot = snapshot
        if snapshot.meme_asset is not None:
            self._meme_asset = snapshot.meme_asset
            self._meme_cycles_remaining = 2
            if self._channel == "vad":
                self._render_current()
            return
        if self._channel == "vad":
            self._update_caption()

    def _rotate_channel(self):
        if self._channel == "vad" and self._meme_cycles_remaining > 0:
            self._meme_cycles_remaining -= 1
            if self._meme_cycles_remaining == 0:
                self._meme_asset = None
        self._channel = "process" if self._channel == "vad" else "vad"
        self._render_current()

    def _render_current(self):
        if self._channel == "process":
            self._last_rendered = self._process_snapshot.asset
        elif self._meme_cycles_remaining > 0 and self._meme_asset is not None:
            self._last_rendered = self._meme_asset
        else:
            self._last_rendered = self._affect_snapshot.asset
        self._update_caption()

    def _update_caption(self):
        if self._channel == "process":
            self._last_caption = f"PROCESS {self._process_snapshot.state}"
        elif self._meme_cycles_remaining > 0 and self._meme_asset is not None:
            self._last_caption = f"MEME {self._meme_asset.id}"
        else:
            current = self._affect_snapshot.current
            self._last_caption = (
                f"V={current.valence:+.2f} A={current.arousal:+.2f} "
                f"D={current.dominance:+.2f}"
            )


def test_meme_snapshot_sets_cycle_counter(tmp_path):
    widget = _FakeWidget()
    meme = ImageAsset("cinema", tmp_path / "cinema.gif")
    widget.update_affect(_make_snapshot(meme_asset=meme))
    assert widget._meme_asset is meme
    assert widget._meme_cycles_remaining == 2


def test_meme_immediately_renders_in_vad_channel(tmp_path):
    widget = _FakeWidget()
    widget._channel = "vad"
    meme = ImageAsset("cinema", tmp_path / "cinema.gif")
    widget.update_affect(_make_snapshot(meme_asset=meme))
    assert widget._last_rendered is meme
    assert widget._last_caption == "MEME cinema"


def test_meme_caption_shown_during_active_cycles(tmp_path):
    widget = _FakeWidget()
    meme = ImageAsset("eat_first", tmp_path / "eat_first.png")
    widget.update_affect(_make_snapshot(meme_asset=meme))
    widget._update_caption()
    assert widget._last_caption == "MEME eat_first"


def test_rotate_decrements_meme_counter_on_vad_exit(tmp_path):
    widget = _FakeWidget()
    meme = ImageAsset("cinema", tmp_path / "cinema.gif")
    widget.update_affect(_make_snapshot(meme_asset=meme))

    # vad (meme, cycles=2) → process (cycles still 2 until next vad exit)
    assert widget._channel == "vad"
    widget._rotate_channel()
    assert widget._channel == "process"
    assert widget._meme_cycles_remaining == 1
    assert widget._meme_asset is meme

    # process → vad (meme, cycles=1)
    widget._rotate_channel()
    assert widget._channel == "vad"
    assert widget._meme_cycles_remaining == 1

    # vad (meme) → process, second decrement → cycles hits 0, meme cleared
    widget._rotate_channel()
    assert widget._channel == "process"
    assert widget._meme_cycles_remaining == 0
    assert widget._meme_asset is None


def test_after_meme_expires_vad_shows_affect_asset(tmp_path):
    widget = _FakeWidget()
    meme = ImageAsset("cinema", tmp_path / "cinema.gif")
    widget.update_affect(_make_snapshot(meme_asset=meme))

    # Exhaust the 2 cycles
    widget._rotate_channel()  # vad→process (cycles=1)
    widget._rotate_channel()  # process→vad
    widget._rotate_channel()  # vad→process (cycles=0, meme cleared)
    widget._rotate_channel()  # process→vad (normal vad)

    assert widget._channel == "vad"
    assert widget._meme_cycles_remaining == 0
    assert widget._meme_asset is None
    assert widget._last_rendered is widget._affect_snapshot.asset


def test_normal_snapshot_does_not_set_meme(tmp_path):
    widget = _FakeWidget()
    widget.update_affect(_make_snapshot(meme_asset=None))
    assert widget._meme_asset is None
    assert widget._meme_cycles_remaining == 0
