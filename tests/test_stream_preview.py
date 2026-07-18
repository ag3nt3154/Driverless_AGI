"""tests/test_stream_preview.py — StreamPreview live-stream widget."""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from tui.streaming import StreamPreview


class _App(App[None]):
    def compose(self) -> ComposeResult:
        yield StreamPreview(id="stream-preview")


def test_hidden_by_default() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            assert w.styles.display == "none"
    asyncio.run(run())


def test_show_progress_makes_visible_and_renders_text() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            w.show_progress("", "Hello wor")
            assert w.styles.display == "block"
            rendered = str(w._render_tail("", "Hello wor"))
            assert "Hello wor" in rendered
    asyncio.run(run())


def test_finish_hides_and_clears() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            w.show_progress("thinking...", "text")
            w.finish()
            assert w.styles.display == "none"
    asyncio.run(run())


def test_render_tail_keeps_only_last_lines() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            long_text = "\n".join(f"line {i}" for i in range(50))
            rendered = str(w._render_tail("", long_text))
            assert "line 49" in rendered          # newest line kept
            assert "line 0" not in rendered       # oldest trimmed
            assert len(rendered.splitlines()) <= StreamPreview.TAIL_LINES
    asyncio.run(run())


def test_render_tail_includes_reasoning_before_text() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            rendered = str(w._render_tail("pondering", "answer"))
            assert rendered.index("pondering") < rendered.index("answer")
    asyncio.run(run())


def test_expand_sets_flex_height_and_clears_max_height() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            w.expand()
            assert w._expanded is True
            assert w.styles.height.unit.name == "FRACTION"
            assert w.styles.max_height is None
    asyncio.run(run())


def test_finish_after_expand_restores_collapsed_css() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            w.expand()
            w.finish()
            assert w._expanded is False
            assert w.styles.height.unit.name == "AUTO"
            assert w.styles.max_height.value == 14
    asyncio.run(run())


def test_finish_without_expand_still_resets_defaults() -> None:
    """finish() must be safe to call on a preview that was never expanded
    (the common case: most stream segments never grow past the 14-row cap)."""
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            w.show_progress("", "hi")
            w.finish()
            assert w._expanded is False
            assert w.styles.display == "none"
    asyncio.run(run())


def test_render_tail_uses_widget_height_when_expanded() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test(size=(80, 40)) as pilot:
            w = app.query_one(StreamPreview)
            w.show_progress("", "hi")   # display: block, so layout gives it real size
            w.expand()
            await pilot.pause()
            assert w.size.height > StreamPreview.TAIL_LINES
            long_text = "\n".join(f"line {i}" for i in range(200))
            rendered = str(w._render_tail("", long_text))
            assert len(rendered.splitlines()) == w.size.height
    asyncio.run(run())
