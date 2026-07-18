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


def test_expand_collapse_cycle_on_real_dagi_app() -> None:
    """Integration check: on a real running DagiApp (not the mocked one used in
    test_tui_callbacks.py), _expand_stream_preview() must hide the real
    ConversationPane AND expand the real StreamPreview simultaneously, and
    _collapse_stream_preview() + preview.finish() must fully restore both
    widgets to their collapsed defaults."""
    async def run() -> None:
        from tui.app import DagiApp
        from tui.conversation import ConversationPane

        app = DagiApp(model_id=None, project=None, verbose=False)
        async with app.run_test(size=(80, 40)) as pilot:
            conversation_pane = app.query_one(ConversationPane)
            preview = app.query_one(StreamPreview)

            app._expand_stream_preview()
            await pilot.pause()
            assert conversation_pane.display is False
            assert preview._expanded is True
            assert preview.styles.height.unit.name == "FRACTION"

            app._collapse_stream_preview()
            preview.finish()
            await pilot.pause()
            assert conversation_pane.display is True
            assert preview.styles.display == "none"
            assert preview._expanded is False
            assert preview.styles.max_height.value == 14
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
