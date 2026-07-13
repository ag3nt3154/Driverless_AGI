"""tests/test_tui_callbacks.py — notify() wiring in build_callbacks()."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from tui.callbacks import build_callbacks


def _make_app():
    """MagicMock DagiApp where call_from_thread runs the callable synchronously,
    and _show_ask_user immediately records an answer and sets the event so
    on_ask_user's evt.wait() doesn't hang."""
    app = MagicMock()

    def call_from_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    app.call_from_thread.side_effect = call_from_thread

    def show_ask_user(question, options, timeout, evt, container):
        container.append("ok")
        evt.set()

    app._show_ask_user.side_effect = show_ask_user
    app._stats = MagicMock(input_tok=0, output_tok=0, cost=0.0, thinking_tok=0)
    app._verbose = False
    return app


class TestNotifyWiring:
    def test_on_ask_user_fires_notify(self):
        app = _make_app()
        with patch("tui.callbacks.notify") as mock_notify:
            callbacks = build_callbacks(app, loop_ref=[])
            callbacks.on_ask_user("What color?", [], None)

        mock_notify.assert_any_call("DAGI has a question", "What color?")

    def test_on_plan_shown_fires_notify(self):
        app = _make_app()
        with patch("tui.callbacks.notify") as mock_notify:
            callbacks = build_callbacks(app, loop_ref=[])
            callbacks.on_plan_shown()

        mock_notify.assert_called_once_with(
            "DAGI's plan is ready", "Review the plan and reply with any changes."
        )

    def test_on_done_fires_notify(self):
        app = _make_app()
        with patch("tui.callbacks.notify") as mock_notify:
            callbacks = build_callbacks(app, loop_ref=[])
            callbacks.on_done("All finished.")

        mock_notify.assert_called_once_with("DAGI is done", "All finished.")

    def test_on_done_with_empty_result_uses_fallback_message(self):
        app = _make_app()
        with patch("tui.callbacks.notify") as mock_notify:
            callbacks = build_callbacks(app, loop_ref=[])
            callbacks.on_done("")

        mock_notify.assert_called_once_with("DAGI is done", "Response complete.")
