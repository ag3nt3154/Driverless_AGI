from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from agent.loop import AgentCallbacks
from pyside_gui.markdown_renderer import render_markdown
from tui.utils import _Stats, _breakdown

worker_log = logging.getLogger("dagi.pyside.worker")


def init_worker_logger(logs_dir: Path) -> None:
    if worker_log.handlers:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(logs_dir / "pyside_worker.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    worker_log.addHandler(handler)
    worker_log.setLevel(logging.DEBUG)


class AgentBridge(QObject):
    """Translates AgentCallbacks into Qt Signals for thread-safe UI updates."""

    tool_started = Signal(str, str)        # name, args
    tool_ended = Signal(str, str)          # name, result
    assistant_text = Signal(str)           # rendered HTML
    reasoning_received = Signal(str)       # text
    token_update = Signal(int, int, object, int, int)
    context_update = Signal(object)        # dict
    stream_started = Signal()
    stream_text_delta = Signal(str)        # chunk
    stream_reasoning_delta = Signal(str)   # chunk
    stream_ended = Signal()
    compaction_done = Signal(int, int)     # kept, removed
    model_switched = Signal(str, str)      # from, to
    error_occurred = Signal(str)           # message
    agent_done = Signal(str)               # result
    agent_paused = Signal()
    ask_user_requested = Signal(str, object, object)  # q, opts, timeout
    expression_changed = Signal(object)
    process_state_changed = Signal(object)
    continue_injected = Signal(int, int)   # cur, max
    plan_shown = Signal()
    subagent_event = Signal(str, str)      # type, json line
    stage_trace = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._stats = _Stats()
        # These three fields are written and read exclusively on the agent worker
        # thread (via callbacks).  Never read them from the Qt main thread.
        self._stream_text = ""
        self._stream_reasoning = ""
        self._handoff_pending = False

    def reset_stats(self) -> None:
        self._stats = _Stats()

    def _emit_token_update(
        self,
        inp: int,
        out: int,
        cost: float | None,
        thinking: int = 0,
        cached: int = 0,
    ) -> None:
        self._stats.update_tokens(inp, out, cost, thinking, cached)
        self.token_update.emit(
            self._stats.input_tok,
            self._stats.output_tok,
            self._stats.cost,
            self._stats.thinking_tok,
            self._stats.cached_tok,
        )

    def _ask_user(self, question: str, options: list, timeout: float | None) -> str:
        evt = threading.Event()
        container: list = []
        self.ask_user_requested.emit(
            question, (options, timeout, evt, container), None,
        )
        # timeout=0 means "auto-select immediately"; add 60s grace for >0.
        # NOTE: avoid `safety or None` — 0.0 is falsy and would block forever.
        if timeout is not None and timeout <= 0:
            safety: float | None = 0.0
        else:
            safety = (timeout + 60.0) if timeout is not None else None
        evt.wait(timeout=safety)
        if container:
            return container[0]
        return next(
            (o["label"] for o in options if o.get("recommended")),
            options[0]["label"] if options else "",
        )

    def _on_stream_start(self) -> None:
        self._stream_text = ""
        self._stream_reasoning = ""
        self.stream_started.emit()

    def _on_stream_text_delta(self, chunk: str) -> None:
        self._stream_text += chunk
        self.stream_text_delta.emit(chunk)

    def _on_reasoning_delta(self, chunk: str) -> None:
        self._stream_reasoning += chunk
        self.stream_reasoning_delta.emit(chunk)

    def _on_stream_end(self) -> None:
        self.stream_ended.emit()

    def _on_done(self, result: str) -> None:
        if self._handoff_pending and result.strip():
            html = render_markdown(result)
            self.assistant_text.emit(html)
        self._handoff_pending = False
        self.agent_done.emit(result)

    def build_callbacks(
        self,
        loop_ref: list | None = None,
    ) -> AgentCallbacks:
        stats = self._stats

        def on_tool_start(name: str, _desc: str, args: str) -> None:
            self.tool_started.emit(name, args)

        def on_tool_end(name: str, result: str) -> None:
            if name == "write_handoff" and self._handoff_pending:
                return
            stats.record_tool(name)
            self.tool_ended.emit(name, result)

        def on_handoff() -> None:
            self._handoff_pending = True

        def on_assistant_text(text: str) -> None:
            if text.strip():
                html = render_markdown(text)
                self.assistant_text.emit(html)

        def on_reasoning(text: str) -> None:
            if text.strip():
                self.reasoning_received.emit(text)

        def on_compaction(kept: int, removed: int) -> None:
            self.compaction_done.emit(kept, removed)
            if loop_ref:
                self.context_update.emit(_breakdown(loop_ref[0]._messages))

        def on_model_switch(from_name: str, to_name: str) -> None:
            self.model_switched.emit(from_name, to_name)

        def on_error(exc: Exception) -> None:
            self.error_occurred.emit(str(exc))

        def on_pause() -> None:
            self.agent_paused.emit()

        def on_api_call(messages: list) -> None:
            self.context_update.emit(_breakdown(messages))

        def on_continue_injected(cur: int, mx: int) -> None:
            self.continue_injected.emit(cur, mx)

        def on_plan_shown() -> None:
            self.plan_shown.emit()

        def on_expression_changed(snapshot) -> None:
            self.expression_changed.emit(snapshot)

        def on_process_state_changed(snapshot) -> None:
            self.process_state_changed.emit(snapshot)

        def on_subagent_factory(subagent_type: str) -> Callable[[str], None]:
            def on_event(line: str) -> None:
                self.subagent_event.emit(subagent_type, line)
            return on_event

        return AgentCallbacks(
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            on_assistant_text=on_assistant_text,
            on_token_update=self._emit_token_update,
            on_iteration=lambda _: None,
            on_done=self._on_done,
            on_error=on_error,
            on_handoff=on_handoff,
            on_api_call=on_api_call,
            on_reasoning=on_reasoning,
            on_compaction=on_compaction,
            on_model_switch=on_model_switch,
            on_ask_user=self._ask_user,
            on_expression_changed=on_expression_changed,
            on_process_state_changed=on_process_state_changed,
            on_subagent_event_factory=on_subagent_factory,
            on_pause=on_pause,
            supports_pause=True,
            on_continue_injected=on_continue_injected,
            on_plan_shown=on_plan_shown,
            on_stream_start=self._on_stream_start,
            on_stream_end=self._on_stream_end,
            on_assistant_text_delta=self._on_stream_text_delta,
            on_reasoning_delta=self._on_reasoning_delta,
        )
