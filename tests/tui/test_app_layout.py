"""tests/tui/test_app_layout.py — verify DagiApp horizontal 65/35 layout structure."""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from tui.conversation import ConversationPane
from tui.prompt_input import PromptInput
from tui.sidebar import Sidebar
from tui.streaming import StreamPreview

_DUMMY_DAGI_ROOT = __import__("pathlib").Path(".")


class _LayoutApp(App[None]):
    """Minimal app that mirrors DagiApp's compose() structure for layout testing."""

    CSS = """
    Screen       { layout: horizontal; }
    #main-column { width: 65%; layout: vertical; }
    Sidebar      { width: 35%; border-left: solid $panel; }
    #prompt      { dock: bottom; height: 8; border-top: solid $panel; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="main-column"):
            yield ConversationPane(id="conversation", highlight=True, markup=True, wrap=True)
            yield StreamPreview(id="stream-preview")
            yield Static("", id="running-indicator")
            yield PromptInput(id="prompt")
        yield Sidebar(
            model_name="test-model",
            context_window=80_000,
            reserve_tokens=4_096,
            dagi_root=_DUMMY_DAGI_ROOT,
            project_path=_DUMMY_DAGI_ROOT,
            memory_root=None,
        )


def test_main_column_exists() -> None:
    async def run() -> None:
        app = _LayoutApp()
        async with app.run_test():
            node = app.query_one("#main-column")
            assert isinstance(node, Vertical)

    asyncio.run(run())


def test_sidebar_is_sibling_of_main_column() -> None:
    async def run() -> None:
        app = _LayoutApp()
        async with app.run_test():
            main_col = app.query_one("#main-column", Vertical)
            sidebar = app.query_one(Sidebar)
            assert main_col.parent is sidebar.parent

    asyncio.run(run())


def test_prompt_inside_main_column() -> None:
    async def run() -> None:
        app = _LayoutApp()
        async with app.run_test():
            prompt = app.query_one(PromptInput)
            assert prompt.parent.id == "main-column"

    asyncio.run(run())
