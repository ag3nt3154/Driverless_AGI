"""Tests for QuestionBroker and build_gui_callbacks."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from agent.affect import AffectSnapshot, AffectVector
from agent.expression_assets import TextFallback
from agent.process_state import ProcessSnapshot
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
        assert evt["type"] == "tool_call"
        assert evt["tool"] == "read"
        assert evt["input"] == {"path": "README.md"}

    def test_tool_end_emits_event(self):
        self.callbacks.on_tool_end("read", "file content here")
        evt = self.writer.last()
        assert evt["type"] == "tool_result"
        assert evt["content"] == "file content here"
        assert evt["is_error"] is False

    def test_assistant_text_emits_message(self):
        self.callbacks.on_assistant_text("Hello there")
        assert self.writer.last()["type"] == "token"
        assert self.writer.last()["text"] == "Hello there"

    def test_empty_assistant_text_suppressed(self):
        self.callbacks.on_assistant_text("   ")
        assert not self.writer.events

    def test_reasoning_emits_message(self):
        self.callbacks.on_reasoning("thinking...")
        assert self.writer.last()["type"] == "thinking"

    def test_empty_reasoning_suppressed(self):
        self.callbacks.on_reasoning("")
        assert not self.writer.events

    def test_token_update_emits_event(self):
        self.callbacks.on_token_update(100, 50, 0.01, 10, 5)
        evt = self.writer.last()
        assert evt["type"] == "cost_update"
        assert evt["total_usd"] == 0.01
        assert evt["session_tokens"] == 160  # 100 + 50 + 10

    def test_iteration_emits_event(self):
        self.callbacks.on_iteration(3)
        assert self.writer.last()["type"] == "turn_start"
        assert self.writer.last()["turn"] == 3

    def test_done_emits_turn_done(self):
        self.callbacks.on_done("task complete")
        types = self.writer.types()
        assert "turn_end" in types
        assert "task_complete" in types
        assert self.writer.last()["result"] == "task complete"

    def test_error_emits_event(self):
        self.callbacks.on_error(RuntimeError("boom"))
        evt = self.writer.last()
        assert evt["type"] == "error"
        assert "boom" in evt["message"]

    def test_api_call_is_noop(self):
        self.callbacks.on_api_call([{"role": "user", "content": "hi"}])
        assert not self.writer.events

    def test_compaction_emits_event(self):
        self.callbacks.on_compaction(10, 5)
        evt = self.writer.last()
        assert evt["type"] == "compact"
        assert evt["kept"] == 10
        assert evt["removed"] == 5

    def test_model_switch_is_noop(self):
        self.callbacks.on_model_switch("gpt-4", "claude-3")
        assert not self.writer.events

    def test_affect_is_noop(self):
        self.callbacks.on_affect_changed(AffectSnapshot(
            baseline=AffectVector(0.0, 0.0, 0.0),
            current=AffectVector(0.1, 0.2, 0.3),
            emote_id="steady",
            asset=TextFallback(Path("default.md"), "test", "DAGI"),
            reason="adjust",
        ))
        assert not self.writer.events

    def test_process_state_is_noop(self):
        self.callbacks.on_process_state_changed(ProcessSnapshot(
            state="thinking",
            asset=TextFallback(Path("default.md"), "test", "DAGI"),
        ))
        assert not self.writer.events

    def test_pause_is_noop(self):
        self.callbacks.on_pause()
        assert not self.writer.events

    def test_continue_injected_is_noop(self):
        self.callbacks.on_continue_injected(2, 10)
        assert not self.writer.events

    def test_plan_shown_is_noop(self):
        self.callbacks.on_plan_shown()
        assert not self.writer.events

    def test_stream_start_is_noop(self):
        self.callbacks.on_stream_start()
        assert not self.writer.events

    def test_stream_end_is_noop(self):
        self.callbacks.on_stream_end()
        assert not self.writer.events

    def test_stream_delta_text(self):
        self.callbacks.on_assistant_text_delta("Hello")
        evt = self.writer.last()
        assert evt["type"] == "token"
        assert evt["text"] == "Hello"

    def test_stream_delta_reasoning(self):
        self.callbacks.on_reasoning_delta("hmm")
        evt = self.writer.last()
        assert evt["type"] == "thinking"
        assert evt["text"] == "hmm"

    def test_supports_pause_is_true(self):
        assert self.callbacks.supports_pause is True

    def test_subagent_event_factory_returns_callable(self):
        fn = self.callbacks.on_subagent_event_factory("explore_files")
        assert callable(fn)

    def test_subagent_event_relay_valid_json(self):
        fn = self.callbacks.on_subagent_event_factory("explore_files")
        fn(json.dumps({"type": "tool_call", "name": "read", "args": "{}"}))
        evt = self.writer.last()
        assert evt["type"] == "subagent"
        assert evt["subagent_type"] == "explore_files"

    def test_subagent_event_relay_invalid_json(self):
        fn = self.callbacks.on_subagent_event_factory("explore_files")
        fn("not json at all")
        evt = self.writer.last()
        assert evt["type"] == "subagent"
        assert evt["subagent_type"] == "explore_files"
        assert evt["event"]["type"] == "raw"
        assert evt["event"]["content"] == "not json at all"
