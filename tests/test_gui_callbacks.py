"""Tests for QuestionBroker and build_gui_callbacks."""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest

from dagi_gui.callbacks import build_gui_callbacks
from dagi_gui.interaction import QuestionBroker
from dagi_gui.protocol import EventWriter, ProtocolError


# ── Test helpers ──────────────────────────────────────────────────────────────

class RecordingWriter:
    """Fake EventWriter that captures events for assertion."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def write(self, event_type: str, **payload: object) -> None:
        self.events.append({"type": event_type, **payload})

    def last(self) -> dict[str, Any]:
        return self.events[-1]

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]


def run_in_thread(fn):
    """Run fn in a thread; return a join()-able with .result."""
    result_box: list = []
    exc_box: list = []

    def wrapper():
        try:
            result_box.append(fn())
        except Exception as e:
            exc_box.append(e)

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()

    class Handle:
        def join(self, timeout=5):
            t.join(timeout=timeout)
            if t.is_alive():
                raise TimeoutError("thread did not complete")
            if exc_box:
                raise exc_box[0]
            return result_box[0] if result_box else None

    return Handle()


# ── QuestionBroker tests ──────────────────────────────────────────────────────

class TestQuestionBroker:
    def test_ask_emits_question_event(self):
        writer = RecordingWriter()
        broker = QuestionBroker(writer)
        handle = run_in_thread(
            lambda: broker.ask("Pick one", [{"label": "A"}], timeout=2)
        )
        import time; time.sleep(0.05)
        qid = writer.last()["question_id"]
        broker.answer(qid, "A")
        handle.join()
        assert writer.events[0]["type"] == "question"
        assert writer.events[0]["text"] == "Pick one"

    def test_ask_returns_answer(self):
        writer = RecordingWriter()
        broker = QuestionBroker(writer)
        handle = run_in_thread(
            lambda: broker.ask("Pick one", [{"label": "A"}], timeout=2)
        )
        import time; time.sleep(0.05)
        qid = writer.last()["question_id"]
        broker.answer(qid, "Alpha")
        assert handle.join() == "Alpha"

    def test_answer_unblocks_only_for_matching_id(self):
        writer = RecordingWriter()
        broker = QuestionBroker(writer)
        handle = run_in_thread(
            lambda: broker.ask("Choose", [], timeout=3)
        )
        import time; time.sleep(0.05)
        with pytest.raises(ProtocolError, match="no pending question"):
            broker.answer("wrong-id", "Alpha")
        qid = writer.last()["question_id"]
        broker.answer(qid, "Alpha")
        assert handle.join() == "Alpha"

    def test_timeout_returns_recommended_option(self):
        writer = RecordingWriter()
        broker = QuestionBroker(writer)
        result = broker.ask(
            "Pick",
            [{"label": "No"}, {"label": "Yes", "recommended": True}],
            timeout=0.01,
        )
        assert result == "Yes"

    def test_timeout_returns_first_label_when_no_recommendation(self):
        writer = RecordingWriter()
        broker = QuestionBroker(writer)
        result = broker.ask(
            "Pick", [{"label": "First"}, {"label": "Second"}], timeout=0.01
        )
        assert result == "First"

    def test_timeout_returns_empty_string_when_no_options(self):
        writer = RecordingWriter()
        broker = QuestionBroker(writer)
        result = broker.ask("Confirm", [], timeout=0.01)
        assert result == ""

    def test_stale_answer_raises_protocol_error(self):
        writer = RecordingWriter()
        broker = QuestionBroker(writer)
        handle = run_in_thread(
            lambda: broker.ask("Pick", [{"label": "A"}], timeout=0.05)
        )
        handle.join()  # let it time out
        import time; time.sleep(0.05)
        with pytest.raises(ProtocolError, match="no pending question"):
            broker.answer("stale-id", "A")

    def test_second_question_gets_new_id(self):
        writer = RecordingWriter()
        broker = QuestionBroker(writer)

        for _ in range(2):
            handle = run_in_thread(
                lambda: broker.ask("Q", [{"label": "A"}], timeout=2)
            )
            import time; time.sleep(0.05)
            qid = writer.last()["question_id"]
            broker.answer(qid, "A")
            handle.join()

        ids = [e["question_id"] for e in writer.events if e["type"] == "question"]
        assert ids[0] != ids[1]


# ── build_gui_callbacks tests ─────────────────────────────────────────────────

class TestBuildGuiCallbacks:
    def setup_method(self):
        self.writer = RecordingWriter()
        self.broker = QuestionBroker(self.writer)
        self.callbacks = build_gui_callbacks(self.writer, self.broker)

    def test_tool_start_emits_event(self):
        self.callbacks.on_tool_start("read", "Read file", '{"path":"README.md"}')
        evt = self.writer.last()
        assert evt["type"] == "tool_start"
        assert evt["name"] == "read"
        assert evt["args"] == '{"path":"README.md"}'

    def test_tool_end_emits_event(self):
        self.callbacks.on_tool_end("read", "file content here")
        evt = self.writer.last()
        assert evt["type"] == "tool_end"
        assert evt["name"] == "read"

    def test_assistant_text_emits_message(self):
        self.callbacks.on_assistant_text("Hello there")
        assert self.writer.last()["type"] == "assistant_message"
        assert self.writer.last()["text"] == "Hello there"

    def test_empty_assistant_text_suppressed(self):
        self.callbacks.on_assistant_text("   ")
        assert not self.writer.events

    def test_reasoning_emits_message(self):
        self.callbacks.on_reasoning("thinking...")
        assert self.writer.last()["type"] == "reasoning_message"

    def test_empty_reasoning_suppressed(self):
        self.callbacks.on_reasoning("")
        assert not self.writer.events

    def test_token_update_emits_event(self):
        self.callbacks.on_token_update(100, 50, 0.01, 10, 5)
        evt = self.writer.last()
        assert evt["type"] == "token_update"
        assert evt["input"] == 100
        assert evt["output"] == 50

    def test_iteration_emits_event(self):
        self.callbacks.on_iteration(3)
        assert self.writer.last()["type"] == "iteration"
        assert self.writer.last()["count"] == 3

    def test_done_emits_turn_done(self):
        self.callbacks.on_done("task complete")
        assert self.writer.last()["type"] == "turn_done"

    def test_error_emits_event(self):
        self.callbacks.on_error(RuntimeError("boom"))
        evt = self.writer.last()
        assert evt["type"] == "error"
        assert "boom" in evt["message"]

    def test_api_call_emits_context_update(self):
        self.callbacks.on_api_call([{"role": "user", "content": "hi"}])
        assert self.writer.last()["type"] == "context_update"

    def test_compaction_emits_event(self):
        self.callbacks.on_compaction(10, 5)
        evt = self.writer.last()
        assert evt["type"] == "compaction"
        assert evt["kept"] == 10
        assert evt["removed"] == 5

    def test_model_switch_emits_event(self):
        self.callbacks.on_model_switch("gpt-4", "claude-3")
        evt = self.writer.last()
        assert evt["type"] == "model_switch"
        assert evt["from_model"] == "gpt-4"
        assert evt["to_model"] == "claude-3"

    def test_emote_emits_event(self):
        self.callbacks.on_emote("thinking", "🤔", False)
        evt = self.writer.last()
        assert evt["type"] == "emote"
        assert evt["name"] == "thinking"

    def test_pause_emits_status(self):
        self.callbacks.on_pause()
        assert self.writer.last()["type"] == "status"
        assert self.writer.last()["state"] == "paused"

    def test_continue_injected_emits_event(self):
        self.callbacks.on_continue_injected(2, 10)
        evt = self.writer.last()
        assert evt["type"] == "continuation"
        assert evt["current"] == 2

    def test_plan_shown_emits_event(self):
        self.callbacks.on_plan_shown()
        assert self.writer.last()["type"] == "plan_ready"

    def test_stream_start_emits_event(self):
        self.callbacks.on_stream_start()
        assert self.writer.last()["type"] == "stream_start"

    def test_stream_end_emits_event(self):
        self.callbacks.on_stream_end()
        assert self.writer.last()["type"] == "stream_end"

    def test_stream_delta_text(self):
        self.callbacks.on_assistant_text_delta("Hello")
        evt = self.writer.last()
        assert evt["type"] == "stream_delta"
        assert evt["kind"] == "assistant"
        assert evt["text"] == "Hello"

    def test_stream_delta_reasoning(self):
        self.callbacks.on_reasoning_delta("hmm")
        evt = self.writer.last()
        assert evt["type"] == "stream_delta"
        assert evt["kind"] == "reasoning"

    def test_supports_pause_is_true(self):
        assert self.callbacks.supports_pause is True

    def test_subagent_event_factory_returns_callable(self):
        fn = self.callbacks.on_subagent_event_factory("explore_files")
        assert callable(fn)

    def test_subagent_event_relay_valid_json(self):
        fn = self.callbacks.on_subagent_event_factory("explore_files")
        fn(json.dumps({"type": "tool_call", "name": "read", "args": "{}"}))
        evt = self.writer.last()
        assert evt["type"] == "subagent_event"
        assert evt["subagent_type"] == "explore_files"

    def test_subagent_event_relay_invalid_json(self):
        fn = self.callbacks.on_subagent_event_factory("explore_files")
        fn("not json at all")
        evt = self.writer.last()
        assert evt["type"] == "subagent_event"
        assert evt["subagent_type"] == "explore_files"
        assert evt["event"]["type"] == "raw"
        assert evt["event"]["content"] == "not json at all"
