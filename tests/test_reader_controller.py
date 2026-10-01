"""tests/test_reader_controller.py — Tests for the sequential reader controller.

Uses a fake provider that answers by request kind (chunk / partial merge /
final merge / shorten), so no real API calls are made. Tests cover:
- reply parsing, line ranges, chunk rendering, excerpt verification
- the chunk loop: constant per-call context, running summary carried forward,
  append-only notes, full coverage, files far larger than the context window
- merging (single call and batched), parent-fit condensation, failures
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import pytest

from tools.read._budgets import ReaderCapacityError, estimate_reader_request
from tools.read._chunking import ReaderChunk
from tools.read._reader_controller import (
    SUMMARY_CHARS,
    ReaderController,
    flag_unverified_excerpts,
    last_line,
    parse_chunk_reply,
    render_chunk,
)
from tools.read._reader_job import ReaderJob, ReaderReturnFormat, render_reader_return
from tools.read._reader_provider import (
    ReaderCancelledError,
    ReaderRuntime,
    build_reader_request,
    emit_reader_progress,
)
from tools.read._selection import ReadSelection, SourceSpan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIGNPOST = "[read_large_file: indexed digest of test selection]"


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
        index=idx, start=0, end=len(text), text=text,
        references=(ref,), estimated_tokens=len(text) // 4,
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
    return config


def _kind(request: dict) -> str:
    content = request["messages"][-1]["content"]
    if "Source chunk" in content:
        return "chunk"
    if "Condense the section notes" in content:
        return "partial"
    if "Write the final index" in content:
        return "final"
    if "Shorten this index" in content:
        return "shorten"
    return "other"


def _default_chunk_reply(request: dict) -> str:
    content = request["messages"][-1]["content"]
    first = content.split("— lines ", 1)[1].split("–", 1)[0]
    return f"<notes>\n### Part (lines {first}–x)\n- point\n</notes>\n<summary>seen {first}</summary>"


class FakeClient:
    """Answers each request with responders[kind](request); records requests."""

    def __init__(self, **responders: Callable[[dict], str]) -> None:
        self.responders = {
            "chunk": _default_chunk_reply,
            "partial": lambda r: "### Merged (lines 1–2)\n- merged point",
            "final": lambda r: "## Overview\nAn overview.\n\n## Index\n| Lines | Section | Contents |",
            **responders,
        }
        self.requests: list[dict] = []
        self.chat = MagicMock()
        self.chat.completions.create = self._create

    def _create(self, **request) -> MagicMock:
        self.requests.append(request)
        text = self.responders[_kind(request)](request)
        choice = MagicMock()
        choice.message.content = text
        choice.message.tool_calls = None
        choice.finish_reason = "stop"
        response = MagicMock()
        response.choices = [choice]
        return response

    def of_kind(self, kind: str) -> list[dict]:
        return [r for r in self.requests if _kind(r) == kind]


def _make_runtime(client: FakeClient) -> ReaderRuntime:
    handoff_tool = MagicMock()
    handoff_tool.run.return_value = "ok"
    return ReaderRuntime(
        client=client,
        model="test-model",
        system_prompt="You are a reader.",
        handoff_tool=handoff_tool,
        api_error_retries=1,
    )


def _make_job(text: str, query: str = "", parent_reserve: int = 8000) -> ReaderJob:
    return ReaderJob(
        version=1,
        selection=_make_selection(text),
        query=query,
        parent_reserve=parent_reserve,
        return_format=ReaderReturnFormat(
            signpost=SIGNPOST, handoff_path=Path("/fake/handoff.md"),
        ),
    )


def _run(text: str, client: FakeClient, *, query: str = "", parent_reserve: int = 8000,
         config: MagicMock | None = None) -> tuple[ReaderController, str]:
    runtime = _make_runtime(client)
    controller = ReaderController(
        job=_make_job(text, query=query, parent_reserve=parent_reserve),
        config=config or _make_config(),
        runtime=runtime,
    )
    controller.run()
    return controller, runtime.handoff_tool.run.call_args[0][0]


def _big_text(lines: int) -> str:
    return "\n".join(f"line {i:06d} lorem ipsum dolor sit amet" for i in range(1, lines + 1))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestParseChunkReply:
    def test_notes_and_summary(self):
        assert parse_chunk_reply("<notes>N</notes>\n<summary>S</summary>") == ("N", "S")

    def test_missing_notes_is_none(self):
        assert parse_chunk_reply("just prose") is None

    def test_empty_notes_is_none(self):
        assert parse_chunk_reply("<notes>  </notes><summary>S</summary>") is None

    def test_missing_summary_gives_empty(self):
        assert parse_chunk_reply("<notes>N</notes>") == ("N", "")

    def test_unclosed_summary_tolerated(self):
        assert parse_chunk_reply("<notes>N</notes><summary>S tail") == ("N", "S tail")


class TestLineRanges:
    def test_last_line_counts_newlines(self):
        chunk = _make_chunk(0, "a\nb\nc\n", line_start=10)
        assert last_line(chunk) == 12

    def test_single_line(self):
        assert last_line(_make_chunk(0, "only", line_start=5)) == 5

    def test_render_chunk_numbers_lines(self):
        out = render_chunk(_make_chunk(0, "a\nb\n", line_start=41))
        assert out == "    41\ta\n    42\tb"


class TestFlagUnverifiedExcerpts:
    SOURCE = "The quick brown fox\njumps over   the lazy dog.\nEnd."

    def test_verbatim_excerpt_untouched(self):
        idx = '> "The quick brown fox" (line 1)'
        assert flag_unverified_excerpts(idx, self.SOURCE) == idx

    def test_whitespace_normalised(self):
        idx = '> "jumps over the lazy dog." (line 2)'
        assert flag_unverified_excerpts(idx, self.SOURCE) == idx

    def test_invented_excerpt_flagged(self):
        idx = '> "The slow red fox" (line 1)'
        assert "not found verbatim" in flag_unverified_excerpts(idx, self.SOURCE)

    def test_ellipsis_pieces_checked_separately(self):
        idx = '> "The quick … lazy dog." (lines 1–2)'
        assert flag_unverified_excerpts(idx, self.SOURCE) == idx

    def test_escaped_inner_quotes_accepted(self):
        source = 'run pip install -e ".[chunking]" first'
        idx = '> "pip install -e \\".[chunking]\\" first" (line 1)'
        assert flag_unverified_excerpts(idx, source) == idx

    def test_other_lines_untouched(self):
        idx = "## Overview\n- a point with \"quotes\"\n| 1–3 | x | y |"
        assert flag_unverified_excerpts(idx, self.SOURCE) == idx


# ---------------------------------------------------------------------------
# Chunk loop
# ---------------------------------------------------------------------------

class TestSingleChunk:
    def test_one_chunk_then_final_merge(self):
        client = FakeClient()
        _, content = _run("hello\nworld", client)
        assert [_kind(r) for r in client.requests] == ["chunk", "final"]
        assert content.startswith(SIGNPOST)
        assert "# file.txt — test selection" in content
        assert "## Overview" in content

    def test_chunk_sent_with_line_numbers(self):
        client = FakeClient()
        _run("hello\nworld", client)
        msg = client.of_kind("chunk")[0]["messages"][-1]["content"]
        assert "     1\thello\n     2\tworld" in msg
        assert "lines 1–2" in msg

    def test_query_in_chunk_and_merge_messages(self):
        client = FakeClient()
        _, content = _run("hello\nworld", client, query="find the greeting")
        for r in client.requests:
            assert "find the greeting" in r["messages"][-1]["content"]
        assert "Query: find the greeting" in content

    def test_no_query_asks_for_general_digest(self):
        client = FakeClient()
        _run("hello", client)
        assert "general digest" in client.requests[0]["messages"][-1]["content"]

    def test_system_prompt_sent(self):
        client = FakeClient()
        _run("hello", client)
        assert client.requests[0]["messages"][0] == {
            "role": "system", "content": "You are a reader.",
        }


class TestManyChunks:
    """Small context window → many chunks."""

    CONFIG = dict(context_window=8_000, reserve_tokens=1_000)

    def test_far_larger_than_context(self):
        text = _big_text(20_000)  # ~200k tokens vs an 8k window
        client = FakeClient()
        controller, _ = _run(text, client, config=_make_config(**self.CONFIG))
        n_chunks = len(controller._state.chunks)
        assert n_chunks > 30
        assert len(client.of_kind("chunk")) == n_chunks
        assert len(controller._state.notes) == n_chunks       # full coverage

    def test_context_per_call_is_bounded(self):
        client = FakeClient()
        _run(_big_text(5_000), client, config=_make_config(**self.CONFIG))
        O = 1_000
        M = math.ceil(1_000 / 8)
        for r in client.of_kind("chunk"):
            assert estimate_reader_request(r) + O + M <= 8_000

    def test_summary_carried_to_next_chunk(self):
        client = FakeClient()
        _run(_big_text(3_000), client, config=_make_config(**self.CONFIG))
        chunk_reqs = client.of_kind("chunk")
        assert "(this is the first chunk)" in chunk_reqs[0]["messages"][-1]["content"]
        assert "seen 1\n" in chunk_reqs[1]["messages"][-1]["content"]
        # Only the latest summary is sent, never earlier chunks' text.
        assert "line 000001 " not in chunk_reqs[2]["messages"][-1]["content"]

    def test_notes_line_ranges_cover_file_in_order(self):
        client = FakeClient()
        controller, _ = _run(_big_text(3_000), client, config=_make_config(**self.CONFIG))
        notes = controller._state.notes
        assert notes[0].first_line == 1
        assert notes[-1].last_line == 3_000
        for prev, nxt in zip(notes, notes[1:]):
            assert nxt.first_line in (prev.last_line, prev.last_line + 1)

    def test_summary_capped(self):
        client = FakeClient(
            chunk=lambda r: "<notes>n</notes><summary>" + "s" * 50_000 + "</summary>"
        )
        controller, _ = _run(_big_text(3_000), client, config=_make_config(**self.CONFIG))
        assert len(controller._state.summary) == SUMMARY_CHARS

    def test_large_notes_merged_in_batches(self):
        fat_notes = (
            "<notes>### S (lines 1–2)\n" + "- detail\n" * 400
            + "</notes><summary>s</summary>"
        )
        client = FakeClient(chunk=lambda r: fat_notes)
        _, content = _run(_big_text(3_000), client, config=_make_config(**self.CONFIG))
        assert client.of_kind("partial")                  # batched first
        assert len(client.of_kind("final")) == 1
        assert "## Overview" in content


class TestUnparseableReply:
    def test_retried_once(self):
        replies = iter(["no tags here", "<notes>N</notes><summary>S</summary>"])
        client = FakeClient(chunk=lambda r: next(replies))
        controller, _ = _run("hello", client)
        assert len(client.of_kind("chunk")) == 2
        assert controller._state.notes[0].notes == "N"

    def test_falls_back_to_raw_reply(self):
        client = FakeClient(chunk=lambda r: "plain prose notes")
        controller, _ = _run("hello", client)
        assert controller._state.notes[0].notes == "plain prose notes"
        assert controller._state.cursor == 1


# ---------------------------------------------------------------------------
# Finalizing
# ---------------------------------------------------------------------------

class TestParentFit:
    def test_oversized_index_is_shortened(self):
        client = FakeClient(
            final=lambda r: "## Overview\n" + "word " * 10_000,
            shorten=lambda r: "## Overview\nshort.",
        )
        _, content = _run("hello", client, parent_reserve=1_000)
        assert client.of_kind("shorten")
        assert content == "## Overview\nshort."

    def test_no_progress_raises(self):
        big = "## Overview\n" + "word " * 10_000
        client = FakeClient(final=lambda r: big, shorten=lambda r: big + "more")
        with pytest.raises(ReaderCapacityError):
            _run("hello", client, parent_reserve=1_000)

    def test_unverified_excerpt_flagged_in_handoff(self):
        client = FakeClient(final=lambda r: '## Overview\n> "not in the file" (line 1)')
        _, content = _run("hello\nworld", client)
        assert "not found verbatim" in content


class TestErrors:
    def test_cancelled_propagates(self):
        client = FakeClient()
        runtime = _make_runtime(client)
        runtime.is_cancelled = lambda: True
        controller = ReaderController(
            job=_make_job("hello"), config=_make_config(), runtime=runtime,
        )
        with pytest.raises(ReaderCancelledError):
            controller.run()

    def test_missing_handoff_tool_raises(self):
        client = FakeClient()
        runtime = _make_runtime(client)
        runtime.handoff_tool = None
        controller = ReaderController(
            job=_make_job("hello"), config=_make_config(), runtime=runtime,
        )
        with pytest.raises(RuntimeError, match="handoff_tool"):
            controller.run()

    def test_context_too_small_raises_before_calls(self):
        client = FakeClient()
        with pytest.raises(ReaderCapacityError):
            _run("hello", client,
                 config=_make_config(context_window=2_500, reserve_tokens=1_000))
        assert client.requests == []


# ---------------------------------------------------------------------------
# Provider helpers
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


