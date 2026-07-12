"""tests/test_prompt_input_multiline.py — Textual pilot tests for PromptInput newline bindings."""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from tui.prompt_input import PromptInput


class _App(App[None]):
    """Minimal host app for PromptInput."""
    submitted: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.submitted = []

    def compose(self) -> ComposeResult:
        yield PromptInput(id="prompt")

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        self.submitted.append(event.value)


def test_ctrl_n_inserts_newline_not_submit() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            widget = app.query_one(PromptInput)
            app.set_focus(widget)
            await pilot.pause()
            await pilot.press("ctrl+n")
            assert widget.text == "\n"
            assert app.submitted == []

    asyncio.run(run())


def test_ctrl_enter_inserts_newline_not_submit() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            widget = app.query_one(PromptInput)
            app.set_focus(widget)
            await pilot.pause()
            await pilot.press("ctrl+enter")
            assert widget.text == "\n"
            assert app.submitted == []

    asyncio.run(run())


def test_shift_enter_inserts_newline_not_submit() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            widget = app.query_one(PromptInput)
            app.set_focus(widget)
            await pilot.pause()
            await pilot.press("shift+enter")
            assert widget.text == "\n"
            assert app.submitted == []

    asyncio.run(run())


def test_enter_with_text_submits_and_clears() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            widget = app.query_one(PromptInput)
            app.set_focus(widget)
            await pilot.pause()
            for char in "hello":
                await pilot.press(char)
            await pilot.press("enter")
            assert app.submitted == ["hello"]
            assert widget.text == ""

    asyncio.run(run())


def test_enter_on_whitespace_only_does_not_submit() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            widget = app.query_one(PromptInput)
            app.set_focus(widget)
            await pilot.pause()
            await pilot.press("ctrl+n")   # inserts "\n"
            await pilot.press("enter")    # should NOT submit — text.strip() == ""
            assert app.submitted == []
            assert widget.text == ""      # load_text("") called, cleared

    asyncio.run(run())


def test_enter_without_text_does_not_submit() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test() as pilot:
            widget = app.query_one(PromptInput)
            app.set_focus(widget)
            await pilot.pause()
            await pilot.press("enter")
            assert app.submitted == []

    asyncio.run(run())
