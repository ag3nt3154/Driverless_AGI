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

    conv = MagicMock()
    app.query_one.return_value = conv
    app._conv = conv  # convenience handle for assertions
    return app


class TestNotifyWiring:
    def test_write_handoff_renders_full_completion_not_filtered_tool_result(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        filtered = "[OUTPUT TRUNCATED]"
        full_markdown = "## Result\n\n" + ("Implemented and verified.\n" * 100)

        callbacks.on_handoff()
        callbacks.on_tool_end("write_handoff", filtered)
        callbacks.on_done(full_markdown)

        app._conv.append_assistant.assert_called_once_with(full_markdown)
        app._conv.append_tool_end.assert_not_called()

    def test_failed_write_handoff_stays_visible_without_deferring_completion(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])

        callbacks.on_tool_end("write_handoff", "Error: cannot write handoff")
        callbacks.on_assistant_text("Fallback response")
        callbacks.on_done("Fallback response")

        app._conv.append_tool_end.assert_called_once_with(
            "write_handoff", "Error: cannot write handoff", False
        )
        app._conv.append_assistant.assert_called_once_with("Fallback response")

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

    def test_on_done_always_writes_visible_conversation_marker(self):
        """on_done must not rely solely on the OS toast — notify() is silently
        skipped whenever the console window has focus (see notifications.py),
        and on_assistant_text no-ops on empty/whitespace text. If on_done never
        touches the conversation pane, a turn that ends with empty content
        (common right after a subagent handoff) produces zero visible signal
        that the agent finished — indistinguishable from a hang."""
        app = _make_app()
        with patch("tui.callbacks.notify"):
            callbacks = build_callbacks(app, loop_ref=[])
            callbacks.on_done("")

        assert app._conv.append_info.called, (
            "on_done must write a visible marker to the conversation pane, "
            "since notify() may be suppressed (window focused) and the "
            "result text may be empty"
        )


class TestStreamingWiring:
    def test_stream_start_resets_and_deltas_update_preview(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("Hello ")
        callbacks.on_reasoning_delta("hmm")
        # show_progress called with ACCUMULATED strings, not raw chunks:
        calls = app._conv.show_progress.call_args_list
        assert calls, "deltas must drive StreamPreview.show_progress"
        last_reasoning, last_text = calls[-1].args
        assert last_text == "Hello "
        assert last_reasoning == "hmm"

    def test_deltas_accumulate_across_calls(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("Hel")
        # Second delta lands inside the 50 ms throttle window → may be skipped,
        # but the forced flush on stream end must still carry the full text:
        callbacks.on_assistant_text_delta("lo")
        # The final flush on stream end always carries the full accumulation:
        callbacks.on_stream_end()
        # stream end hides the preview:
        assert app._conv.finish.called
        # and the last show_progress before it saw the full text:
        last_reasoning, last_text = app._conv.show_progress.call_args_list[-1].args
        assert last_text == "Hello"

    def test_stream_end_always_finishes_preview(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_stream_end()
        assert app._conv.finish.called

    def test_second_stream_starts_clean(self):
        """A new stream must not inherit the previous turn's text."""
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("first turn")
        callbacks.on_stream_end()
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("second")
        callbacks.on_stream_end()
        _, last_text = app._conv.show_progress.call_args_list[-1].args
        assert last_text == "second"
        assert "first turn" not in last_text

    def test_first_delta_expands_stream_preview(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("Hello")
        assert app._expand_stream_preview.called

    def test_expand_fires_only_once_per_segment(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("Hel")
        callbacks.on_assistant_text_delta("lo")
        callbacks.on_reasoning_delta("hmm")
        assert app._expand_stream_preview.call_count == 1

    def test_stream_end_collapses_when_expanded(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("Hello")
        callbacks.on_stream_end()
        assert app._collapse_stream_preview.called

    def test_stream_end_does_not_collapse_when_never_expanded(self):
        """A stream segment with zero deltas (e.g. straight to a tool call)
        never expanded ConversationPane's sibling, so it must not toggle it
        back on either — there's nothing to undo."""
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_stream_end()
        assert not app._collapse_stream_preview.called

    def test_second_segment_expands_independently(self):
        """Each stream segment tracks its own expanded state from a clean
        slate — a segment that didn't expand mustn't suppress expansion on
        the next one, and vice versa."""
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_stream_end()  # no deltas: never expanded
        app._expand_stream_preview.reset_mock()
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("now streaming")
        assert app._expand_stream_preview.called
