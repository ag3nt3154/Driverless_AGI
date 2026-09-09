"""tests/test_reader_controller.py — Tests for the sequential reader controller.

Uses a scripted fake provider (a callable returning predetermined text) so
no real API calls are made. Tests cover:
- ReaderState initialization and invariants
- ReaderController full run with a happy-path fake provider
- Coverage tracking (cursor advances, covered list)
- Condensation trigger when digest exceeds parent reserve
- ReaderCapacityError raised when preflight detects impossible budgets
- preflight_reader edge cases (skeleton overflow, history overflow)
"""
from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.read._budgets import (
    ReaderCapacityError,
    ReaderLimits,
    SummaryAllocation,
    preflight_reader,
)
from tools.read._chunking import ReaderChunk
from tools.read._reader_controller import (
    ReaderController,
    ReaderState,
    _chunk_token_budget,
)
from tools.read._reader_job import ReaderJob, ReaderReturnFormat, render_reader_return
from tools.read._reader_provider import (
    ReaderCancelledError,
    ReaderProviderError,
    ReaderRuntime,
    build_reader_request,
    emit_reader_progress,
)
from tools.read._selection import ReadSelection, SourceSpan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_selection(text: str, line_start: int = 1) -> ReadSelection:
    span = SourceSpan(start=0, end=len(text), source_start=0, line_start=line_start)
    return ReadSelection(
        path=Path("/fake/file.txt"),
        text=text,
        spans=(span,),
        header=None,
        editable_path=None,
        scope="test selection",
    )


def _make_chunk(idx: int, text: str, line_start: int = 1) -> ReaderChunk:
    ref = SourceSpan(start=0, end=len(text), source_start=0, line_start=line_start)
    return ReaderChunk(
        index=idx,
        start=0,
        end=len(text),
        text=text,
        references=(ref,),
        estimated_tokens=len(text) // 4,
    )


def _make_return_format(parent_reserve: int = 8000) -> ReaderReturnFormat:
    return ReaderReturnFormat(
        signpost="[test file too large. Delegated to reader. Summary below.]",
        handoff_path=Path("/fake/handoff.md"),
    )


def _make_limits(
    parent_reserve: int = 8000,
    context_window: int = 200_000,
    output_reserve: int = 16_384,
    max_repairs: int = 3,
) -> ReaderLimits:
    return ReaderLimits(
        parent_reserve=parent_reserve,
        context_window=context_window,
        output_reserve=output_reserve,
        estimator_margin=math.ceil(output_reserve / 8),
        max_repairs=max_repairs,
    )


def _make_config(
    context_window: int = 200_000,
    reserve_tokens: int = 16_384,
    max_continuations: int = 3,
) -> MagicMock:
    config = MagicMock()
    config.context_window = context_window
    config.reserve_tokens = reserve_tokens
    config.max_output_tokens = None
    config.max_continuations = max_continuations
    config.api_error_retries = 1
    config.request_kwargs = {}
    config.model = "test-model"
    config.system_prompt = "You are a reader."
    return config


class ScriptedClient:
    """Fake API client that returns responses from a predetermined script."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.chat = MagicMock()
        self.chat.completions = MagicMock()
        self.chat.completions.create = self._create

    def _create(self, **kwargs) -> MagicMock:
        if self._index >= len(self._responses):
            raise ReaderProviderError("ScriptedClient ran out of responses")
        text = self._responses[self._index]
        self._index += 1
        choice = MagicMock()
        choice.message.content = text
        choice.message.tool_calls = None
        choice.finish_reason = "stop"
        response = MagicMock()
        response.choices = [choice]
        return response

    @property
    def call_count(self) -> int:
        return self._index


def _make_runtime(responses: list[str], parent_reserve: int = 8000) -> ReaderRuntime:
    client = ScriptedClient(responses)
    handoff_tool = MagicMock()
    handoff_tool.run.return_value = "ok"
    return ReaderRuntime(
        client=client,
        model="test-model",
        system_prompt="You are a reader.",
        handoff_tool=handoff_tool,
        api_error_retries=1,
    )


def _make_job(
    text: str,
    query: str = "",
    parent_reserve: int = 8000,
) -> ReaderJob:
    selection = _make_selection(text)
    return ReaderJob(
        version=1,
        selection=selection,
        query=query,
        parent_reserve=parent_reserve,
        return_format=_make_return_format(parent_reserve),
    )


# ---------------------------------------------------------------------------
# ReaderState
# ---------------------------------------------------------------------------

class TestReaderState:
    def test_default_state(self):
        state = ReaderState()
        assert state.cursor == 0
        assert state.digest == ""
        assert state.covered == []
        assert state.repairs == 0

    def test_state_is_mutable(self):
        state = ReaderState()
        state.cursor = 1
        state.covered.append(0)
        assert state.cursor == 1
        assert 0 in state.covered


# ---------------------------------------------------------------------------
# render_reader_return
# ---------------------------------------------------------------------------

class TestRenderReaderReturn:
    def test_combines_signpost_and_content(self):
        fmt = ReaderReturnFormat(
            signpost="[large file. Summary below.]",
            handoff_path=Path("/h.md"),
        )
        result = render_reader_return("digest text", fmt)
        assert result.startswith("[large file. Summary below.]")
        assert "digest text" in result

    def test_signpost_on_first_line(self):
        fmt = ReaderReturnFormat(signpost="[s]", handoff_path=Path("/h.md"))
        lines = render_reader_return("body", fmt).splitlines()
        assert lines[0] == "[s]"


# ---------------------------------------------------------------------------
# build_reader_request
# ---------------------------------------------------------------------------

class TestBuildReaderRequest:
    def test_system_prompt_first(self):
        runtime = _make_runtime(["ok"])
        req = build_reader_request([], runtime=runtime, output_tokens=100)
        assert req["messages"][0]["role"] == "system"
        assert req["messages"][0]["content"] == "You are a reader."

    def test_max_tokens_set(self):
        runtime = _make_runtime(["ok"])
        req = build_reader_request([], runtime=runtime, output_tokens=512)
        assert req["max_tokens"] == 512

    def test_no_tools_by_default(self):
        runtime = _make_runtime(["ok"])
        req = build_reader_request([], runtime=runtime, output_tokens=100)
        assert "tools" not in req

    def test_tools_included_when_requested(self):
        runtime = _make_runtime(["ok"])
        runtime.schemas = [{"name": "write_handoff"}]
        req = build_reader_request(
            [], runtime=runtime, output_tokens=100, include_tools=True
        )
        assert "tools" in req

    def test_messages_appended_after_system(self):
        runtime = _make_runtime(["ok"])
        msgs = [{"role": "user", "content": "hello"}]
        req = build_reader_request(msgs, runtime=runtime, output_tokens=100)
        roles = [m["role"] for m in req["messages"]]
        assert roles[0] == "system"
        assert "user" in roles


# ---------------------------------------------------------------------------
# emit_reader_progress
# ---------------------------------------------------------------------------

class TestEmitReaderProgress:
    def test_calls_on_assistant_text(self):
        callbacks = MagicMock()
        emit_reader_progress(callbacks, completed=1, total=3, phase="reading")
        callbacks.on_assistant_text.assert_called_once()
        text = callbacks.on_assistant_text.call_args[0][0]
        assert "reading" in text
        assert "1/3" in text

    def test_none_callbacks_no_crash(self):
        emit_reader_progress(None, completed=0, total=1, phase="reading")

    def test_missing_callback_attr_no_crash(self):
        callbacks = object()  # no on_assistant_text attr
        emit_reader_progress(callbacks, completed=0, total=1, phase="reading")


# ---------------------------------------------------------------------------
# preflight_reader
# ---------------------------------------------------------------------------

class TestPreflightReader:
    def _chunks(self, n: int, token_estimate: int = 100) -> tuple[ReaderChunk, ...]:
        return tuple(_make_chunk(i, "x" * (token_estimate * 4)) for i in range(n))

    def test_happy_path_returns_allocation(self):
        limits = _make_limits(parent_reserve=8000)
        fmt = _make_return_format()
        chunks = self._chunks(2, token_estimate=100)
        base_req: dict = {}
        alloc = preflight_reader(base_req, chunks, limits=limits, return_format=fmt)
        assert isinstance(alloc, SummaryAllocation)
        assert len(alloc.section_chars) == 2
        assert alloc.skeleton_chars > 0

    def test_skeleton_exceeds_parent_reserve_raises(self):
        # Make parent_reserve tiny so the skeleton alone overflows
        limits = _make_limits(parent_reserve=1)
        fmt = ReaderReturnFormat(
            signpost="[" + "x" * 200 + "]",
            handoff_path=Path("/h.md"),
        )
        chunks = self._chunks(10, token_estimate=100)
        with pytest.raises(ReaderCapacityError) as exc_info:
            preflight_reader({}, chunks, limits=limits, return_format=fmt)
        assert exc_info.value.available_tokens == 1

    def test_context_overflow_raises(self):
        # Make context_window very small
        limits = _make_limits(
            parent_reserve=8000,
            context_window=1000,
            output_reserve=500,
        )
        fmt = _make_return_format()
        # Many large chunks will overflow C
        chunks = self._chunks(20, token_estimate=200)
        with pytest.raises(ReaderCapacityError):
            preflight_reader({}, chunks, limits=limits, return_format=fmt)

    def test_empty_chunks_returns_empty_allocation(self):
        limits = _make_limits()
        fmt = _make_return_format()
        alloc = preflight_reader({}, (), limits=limits, return_format=fmt)
        assert alloc.section_chars == ()

    def test_section_chars_sum_positive(self):
        limits = _make_limits(parent_reserve=8000)
        fmt = _make_return_format()
        chunks = self._chunks(3, token_estimate=50)
        alloc = preflight_reader({}, chunks, limits=limits, return_format=fmt)
        assert sum(alloc.section_chars) > 0

    def test_recommendation_on_skeleton_overflow(self):
        limits = _make_limits(parent_reserve=1)
        fmt = ReaderReturnFormat(signpost="[" + "x" * 200 + "]", handoff_path=Path("/h.md"))
        with pytest.raises(ReaderCapacityError) as exc_info:
            preflight_reader({}, self._chunks(5), limits=limits, return_format=fmt)
        assert exc_info.value.recommendation in (
            ReaderCapacityError.NARROW_RANGE,
            ReaderCapacityError.LARGER_MODEL,
            ReaderCapacityError.FEWER_PAGES,
        )


# ---------------------------------------------------------------------------
# _chunk_token_budget
# ---------------------------------------------------------------------------

class TestChunkTokenBudget:
    def test_positive_budget(self):
        limits = _make_limits(context_window=200_000, output_reserve=16_384)
        k = _chunk_token_budget(limits)
        assert k > 0

    def test_budget_capped_by_output_reserve(self):
        limits = _make_limits(output_reserve=1000)
        k = _chunk_token_budget(limits)
        assert k <= 1000

    def test_impossible_limits_raises(self):
        limits = _make_limits(
            context_window=1000,
            output_reserve=900,
        )
        # C - O - M = 1000 - 900 - ceil(900/8) = 1000 - 900 - 113 = -13 < 0
        with pytest.raises(ReaderCapacityError):
            _chunk_token_budget(limits)


# ---------------------------------------------------------------------------
# ReaderController: full run (happy path)
# ---------------------------------------------------------------------------

class TestReaderControllerHappyPath:
    def test_single_chunk_run(self):
        text = "This is a test document with some content. " * 20
        job = _make_job(text, parent_reserve=8000)
        # One response for the chunk summary
        runtime = _make_runtime(["Summary of the test document."])
        config = _make_config()

        with patch(
            "tools.read._reader_controller.chunk_selection",
            return_value=(
                _make_chunk(0, text),
            ),
        ), patch(
            "tools.read._reader_controller.preflight_reader",
            return_value=SummaryAllocation(
                section_chars=(2000,),
                skeleton_chars=100,
            ),
        ), patch(
            "tools.read._reader_controller.resolve_reader_limits",
            return_value=_make_limits(),
        ):
            controller = ReaderController(job=job, config=config, runtime=runtime)
            controller.run()

        runtime.handoff_tool.run.assert_called_once()
        content = runtime.handoff_tool.run.call_args[0][0]
        assert "Summary of the test document." in content

    def test_two_chunk_run(self):
        text = "chunk A content. " * 30
        job = _make_job(text, parent_reserve=8000)
        runtime = _make_runtime(["Summary A.", "Summary B."])
        config = _make_config()

        chunks = (_make_chunk(0, "chunk A"), _make_chunk(1, "chunk B"))

        with patch("tools.read._reader_controller.chunk_selection", return_value=chunks), \
             patch("tools.read._reader_controller.preflight_reader",
                   return_value=SummaryAllocation(section_chars=(1000, 1000), skeleton_chars=80)), \
             patch("tools.read._reader_controller.resolve_reader_limits",
                   return_value=_make_limits()):
            controller = ReaderController(job=job, config=config, runtime=runtime)
            controller.run()

        # Both summaries should appear in handoff content
        content = runtime.handoff_tool.run.call_args[0][0]
        assert "Summary A." in content
        assert "Summary B." in content

    def test_cursor_advances_in_order(self):
        text = "data " * 50
        job = _make_job(text)
        runtime = _make_runtime(["S1.", "S2.", "S3."])
        config = _make_config()
        chunks = tuple(_make_chunk(i, f"chunk {i}") for i in range(3))

        cursor_snapshots = []

        original_append = ReaderController._append_section

        def tracking_append(self, chunk_index, summary, chunk):
            cursor_snapshots.append(self._state.cursor)
            original_append(self, chunk_index, summary, chunk)

        with patch("tools.read._reader_controller.chunk_selection", return_value=chunks), \
             patch("tools.read._reader_controller.preflight_reader",
                   return_value=SummaryAllocation(
                       section_chars=(1000, 1000, 1000), skeleton_chars=60)), \
             patch("tools.read._reader_controller.resolve_reader_limits",
                   return_value=_make_limits()), \
             patch.object(ReaderController, "_append_section", tracking_append):
            controller = ReaderController(job=job, config=config, runtime=runtime)
            controller.run()

        assert cursor_snapshots == [0, 1, 2]

    def test_covered_list_filled(self):
        text = "data " * 30
        job = _make_job(text)
        runtime = _make_runtime(["S1.", "S2."])
        config = _make_config()
        chunks = (_make_chunk(0, "A"), _make_chunk(1, "B"))

        with patch("tools.read._reader_controller.chunk_selection", return_value=chunks), \
             patch("tools.read._reader_controller.preflight_reader",
                   return_value=SummaryAllocation(
                       section_chars=(1000, 1000), skeleton_chars=60)), \
             patch("tools.read._reader_controller.resolve_reader_limits",
                   return_value=_make_limits()):
            controller = ReaderController(job=job, config=config, runtime=runtime)
            controller.run()

        assert controller._state.covered == [0, 1]

    def test_query_passed_in_user_message(self):
        text = "content " * 20
        job = _make_job(text, query="find references to foo")
        chunks = (_make_chunk(0, text),)

        messages_sent = []
        real_build = build_reader_request

        def capture_build(msgs, **kw):
            messages_sent.append(msgs)
            return real_build(msgs, **kw)

        with patch("tools.read._reader_controller.chunk_selection", return_value=chunks), \
             patch("tools.read._reader_controller.preflight_reader",
                   return_value=SummaryAllocation(section_chars=(2000,), skeleton_chars=60)), \
             patch("tools.read._reader_controller.resolve_reader_limits",
                   return_value=_make_limits()), \
             patch("tools.read._reader_controller.build_reader_request", capture_build), \
             patch("tools.read._reader_controller.call_reader", return_value="summary"):
            runtime = _make_runtime([])
            config = _make_config()
            controller = ReaderController(job=job, config=config, runtime=runtime)
            controller.run()

        # At least one message should contain the query
        all_content = " ".join(
            str(m) for batch in messages_sent for m in batch
        )
        assert "find references to foo" in all_content


# ---------------------------------------------------------------------------
# ReaderController: condensation
# ---------------------------------------------------------------------------

class TestReaderControllerCondensation:
    def test_condensation_triggered_when_oversized(self):
        # parent_reserve=100: up to 400 chars → F(digest)>=100 triggers condensation.
        # Section summary is 500 chars → F=125 >= 100 → condensation fires.
        # Condensed "short x" * 10 → ~70 chars → F=17 < 100 → succeeds.
        text = "data " * 20
        parent_reserve = 100
        job = _make_job(text, parent_reserve=parent_reserve)

        section_summary = "verbose " * 63  # ~504 chars → F≈126 ≥ 100
        condensed = "brief " * 10          # 60 chars → F=15 < 100

        runtime = _make_runtime([section_summary, condensed])
        config = _make_config()
        chunk = _make_chunk(0, text)

        with patch("tools.read._reader_controller.chunk_selection", return_value=(chunk,)), \
             patch("tools.read._reader_controller.preflight_reader",
                   return_value=SummaryAllocation(section_chars=(10000,), skeleton_chars=60)), \
             patch("tools.read._reader_controller.resolve_reader_limits",
                   return_value=_make_limits(parent_reserve=parent_reserve)):
            controller = ReaderController(job=job, config=config, runtime=runtime)
            controller.run()

        # condense should have been called (client used 2 responses)
        assert runtime.client.call_count == 2

    def test_condensation_no_progress_raises(self):
        # If condense returns same-length text, fails immediately (no-progress).
        # parent_reserve=100 → up to 400 chars. Both summary and condensed are
        # 500 chars → F=125 >= 100 → condensation fires; same-length → no progress.
        text = "data " * 10
        parent_reserve = 100
        job = _make_job(text, parent_reserve=parent_reserve)

        long_summary = "x" * 500  # F=125 >= 100 → triggers condensation
        same_length  = "y" * 500  # same length → no progress → raises

        runtime = _make_runtime([long_summary, same_length])
        config = _make_config(max_continuations=5)
        chunk = _make_chunk(0, text)

        with patch("tools.read._reader_controller.chunk_selection", return_value=(chunk,)), \
             patch("tools.read._reader_controller.preflight_reader",
                   return_value=SummaryAllocation(section_chars=(50000,), skeleton_chars=60)), \
             patch("tools.read._reader_controller.resolve_reader_limits",
                   return_value=_make_limits(parent_reserve=parent_reserve)):
            controller = ReaderController(job=job, config=config, runtime=runtime)
            with pytest.raises(ReaderCapacityError):
                controller.run()


# ---------------------------------------------------------------------------
# ReaderController: error conditions
# ---------------------------------------------------------------------------

class TestReaderControllerErrors:
    def test_cancelled_during_read_propagates(self):
        text = "data " * 10
        job = _make_job(text)
        config = _make_config()

        runtime = _make_runtime([])
        runtime.is_cancelled = lambda: True  # always cancelled

        chunk = _make_chunk(0, text)

        with patch("tools.read._reader_controller.chunk_selection", return_value=(chunk,)), \
             patch("tools.read._reader_controller.preflight_reader",
                   return_value=SummaryAllocation(section_chars=(2000,), skeleton_chars=60)), \
             patch("tools.read._reader_controller.resolve_reader_limits",
                   return_value=_make_limits()):
            controller = ReaderController(job=job, config=config, runtime=runtime)
            with pytest.raises(ReaderCancelledError):
                controller.run()

    def test_missing_handoff_tool_raises(self):
        text = "data " * 10
        job = _make_job(text)
        config = _make_config()

        runtime = _make_runtime(["summary"])
        runtime.handoff_tool = None  # remove handoff tool

        chunk = _make_chunk(0, text)

        with patch("tools.read._reader_controller.chunk_selection", return_value=(chunk,)), \
             patch("tools.read._reader_controller.preflight_reader",
                   return_value=SummaryAllocation(section_chars=(2000,), skeleton_chars=60)), \
             patch("tools.read._reader_controller.resolve_reader_limits",
                   return_value=_make_limits()):
            controller = ReaderController(job=job, config=config, runtime=runtime)
            with pytest.raises(RuntimeError, match="handoff_tool"):
                controller.run()

    def test_preflight_failure_stops_before_api_calls(self):
        text = "data " * 10
        job = _make_job(text, parent_reserve=1)  # too small
        config = _make_config()
        runtime = _make_runtime(["should not be called"])

        with patch("tools.read._reader_controller.chunk_selection",
                   return_value=(_make_chunk(0, text),)), \
             patch("tools.read._reader_controller.resolve_reader_limits",
                   return_value=_make_limits(parent_reserve=1)), \
             patch("tools.read._reader_controller.preflight_reader",
                   side_effect=ReaderCapacityError(
                       required_tokens=9999,
                       available_tokens=1,
                       recommendation=ReaderCapacityError.NARROW_RANGE,
                   )):
            controller = ReaderController(job=job, config=config, runtime=runtime)
            with pytest.raises(ReaderCapacityError):
                controller.run()

        # No API calls should have been made
        assert runtime.client.call_count == 0
