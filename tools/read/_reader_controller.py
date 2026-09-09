"""tools/read/_reader_controller.py — Sequential reader controller.

Deterministic read loop inside the reader subprocess. The controller owns its
accumulated conversation, coverage ledger, and digest. No automatic compaction,
no nested agents, no parallel reads.

Entry point for the subprocess: run_reader_job_mode(args) is called from
tools/subagent_main.py with at most 5 lines of routing code.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from tools.read._budgets import (
    ReaderCapacityError,
    ReaderLimits,
    SummaryAllocation,
    preflight_reader,
    require_parent_fit,
    resolve_reader_limits,
)
from tools.read._chunking import ReaderChunk, chunk_selection
from tools.read._reader_job import ReaderJob, ReaderReturnFormat, render_reader_return
from tools.read._reader_provider import (
    ReaderRuntime,
    ReaderCancelledError,
    ReaderProviderError,
    build_reader_request,
    call_reader,
    emit_reader_progress,
)

if TYPE_CHECKING:
    from agent._loop_config import AgentConfig


# ---------------------------------------------------------------------------
# Mutable controller state
# ---------------------------------------------------------------------------

@dataclass
class ReaderState:
    """All mutable accumulation owned by the controller.

    messages      Accumulated conversation turns (user source + assistant summaries).
    chunks        Ordered, immutable chunk sequence for this invocation.
    cursor        Index of the next chunk to read (0 = none read yet).
    digest        Accumulated rendered digest (grows per committed section).
    remaining_chars Parent prose capacity remaining (starts at allocation total).
    repairs       Number of condensation / repair attempts consumed.
    covered       Chunk indices that have been committed (append-only).
    """
    messages: list[dict] = field(default_factory=list)
    chunks: tuple[ReaderChunk, ...] = field(default_factory=tuple)
    cursor: int = 0
    digest: str = ""
    remaining_chars: int = 0
    repairs: int = 0
    covered: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class ReaderController:
    """Sequential deterministic reader for one ReaderJob.

    Drives the read loop: preflight → read each chunk → finalize → handoff.
    Never emits a successful handoff on incomplete coverage. Raises on any
    unrecoverable error so the caller can emit a clear failure event.
    """

    _SECTION_PROMPT = (
        "Summarize ONLY the source chunk above. Do not repeat or reference "
        "previous summaries. Focus on the content in this chunk. Be concise."
    )
    _CONDENSE_PROMPT = (
        "The current digest is too large for the parent context. Produce a "
        "condensed version that is strictly shorter. Preserve ALL covered chunk "
        "references. Do not add new content."
    )

    def __init__(
        self,
        *,
        job: ReaderJob,
        config: "AgentConfig",
        runtime: ReaderRuntime,
    ) -> None:
        self._job = job
        self._config = config
        self._runtime = runtime
        self._state = ReaderState()

    def run(self) -> None:
        """Full controller lifecycle: preflight, read all chunks, finalize.

        Raises ReaderCapacityError, ReaderCancelledError, or RuntimeError on
        failure. The caller (run_reader_job_mode) formats these into the
        subprocess error exit.
        """
        limits = resolve_reader_limits(
            self._job.parent_reserve,
            self._config,
            request_kwargs=self._runtime.request_options,
        )

        self._state.chunks = chunk_selection(
            self._job.selection,
            chunk_tokens=_chunk_token_budget(limits),
        )

        if not self._state.chunks:
            raise RuntimeError("chunk_selection returned no chunks for non-empty selection")

        base_req = build_reader_request(
            [], runtime=self._runtime, output_tokens=limits.output_reserve,
        )
        allocation = preflight_reader(
            base_req,
            self._state.chunks,
            limits=limits,
            return_format=self._job.return_format,
        )

        self._state.remaining_chars = sum(allocation.section_chars)
        total = len(self._state.chunks)

        for i in range(total):
            emit_reader_progress(
                self._runtime.callbacks,
                completed=i,
                total=total,
                phase="reading",
            )
            self._read_next(limits, allocation.section_chars[i])

        emit_reader_progress(
            self._runtime.callbacks, completed=total, total=total, phase="finalizing",
        )
        content = self._finalize(limits)
        self._write_handoff(content)

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _read_next(self, limits: ReaderLimits, section_chars: int) -> None:
        """Append one source chunk as a user message, call provider, commit summary."""
        chunk = self._state.chunks[self._state.cursor]

        user_msg: dict = {
            "role": "user",
            "content": (
                f"Source chunk {chunk.index + 1}/{len(self._state.chunks)} "
                f"(lines {_first_line(chunk)}–{_last_line(chunk)}):\n\n"
                f"{chunk.text}\n\n"
                f"{self._SECTION_PROMPT}"
            ),
        }
        if self._job.query:
            user_msg["content"] += f"\n\nFocus query: {self._job.query}"

        messages_so_far = list(self._state.messages) + [user_msg]
        req = build_reader_request(
            messages_so_far,
            runtime=self._runtime,
            output_tokens=min(section_chars // 4 + 1, limits.output_reserve),
        )
        summary = call_reader(req, runtime=self._runtime, limits=limits)
        summary = summary[:section_chars] if len(summary) > section_chars else summary

        self._append_section(chunk.index, summary, chunk)
        self._state.messages = messages_so_far + [
            {"role": "assistant", "content": summary}
        ]

    def _append_section(self, chunk_index: int, summary: str, chunk: ReaderChunk) -> None:
        """Commit one section summary to the digest, advancing the cursor atomically."""
        if chunk_index != self._state.cursor:
            raise RuntimeError(
                f"Out-of-order commit: expected cursor {self._state.cursor}, "
                f"got chunk_index {chunk_index}"
            )
        ref = _chunk_ref_line(chunk)
        section = f"{ref}\n{summary}"
        self._state.digest = (
            self._state.digest + "\n\n" + section
            if self._state.digest else section
        )
        self._state.covered.append(chunk_index)
        self._state.remaining_chars -= len(summary)
        self._state.cursor += 1

    def _finalize(self, limits: ReaderLimits) -> str:
        """Verify full coverage and return the renderable digest content.

        If the rendered return is too large for the parent, attempts bounded
        condensation in the same conversation.
        """
        if self._state.cursor != len(self._state.chunks):
            raise RuntimeError(
                f"Finalize called with cursor {self._state.cursor} "
                f"but {len(self._state.chunks)} chunks total"
            )

        content = self._job.return_format.signpost + "\n\n" + self._state.digest

        try:
            require_parent_fit(content, self._job.parent_reserve)
            return content
        except ReaderCapacityError:
            pass  # try condensation

        return self._condense(
            limits,
            target_chars=self._job.parent_reserve * 4 - len(self._job.return_format.signpost) - 4,
        )

    def _condense(self, limits: ReaderLimits, target_chars: int) -> str:
        """Ask the model to condense the digest until it fits, or fail."""
        if target_chars <= 0:
            raise ReaderCapacityError(
                required_tokens=len(self._state.digest) // 4,
                available_tokens=self._job.parent_reserve,
                recommendation=ReaderCapacityError.NARROW_RANGE,
            )

        prev_len = len(self._state.digest)
        for _ in range(max(0, self._config.max_continuations)):
            user_msg = {
                "role": "user",
                "content": (
                    f"{self._CONDENSE_PROMPT}\n\n"
                    f"Target: under {target_chars} characters.\n\n"
                    f"Current digest:\n{self._state.digest}"
                ),
            }
            messages_so_far = list(self._state.messages) + [user_msg]
            req = build_reader_request(
                messages_so_far,
                runtime=self._runtime,
                output_tokens=min(target_chars // 4 + 1, limits.output_reserve),
            )
            try:
                condensed = call_reader(req, runtime=self._runtime, limits=limits)
            except (ReaderProviderError, ReaderCapacityError):
                break

            if len(condensed) >= prev_len:
                break  # no progress — fail immediately

            prev_len = len(condensed)
            self._state.messages = messages_so_far + [
                {"role": "assistant", "content": condensed}
            ]
            content = self._job.return_format.signpost + "\n\n" + condensed
            try:
                require_parent_fit(content, self._job.parent_reserve)
                return content
            except ReaderCapacityError:
                self._state.digest = condensed
                self._state.repairs += 1

        raise ReaderCapacityError(
            required_tokens=len(self._state.digest) // 4,
            available_tokens=self._job.parent_reserve,
            recommendation=ReaderCapacityError.NARROW_RANGE,
        )

    def _write_handoff(self, content: str) -> None:
        """Write the handoff file via handoff_tool and emit completion event."""
        if self._runtime.handoff_tool is None:
            raise RuntimeError("handoff_tool is not set on ReaderRuntime")
        result = self._runtime.handoff_tool.run(content)
        on_done = getattr(self._runtime.callbacks, "on_done", None) if self._runtime.callbacks else None
        if callable(on_done):
            on_done(result or "")


# ---------------------------------------------------------------------------
# Subprocess entry point (<=5 lines of routing in subagent_main.py)
# ---------------------------------------------------------------------------

def run_reader_job_mode(args: Any) -> None:
    """Entry point called from tools/subagent_main.py after job-path validation.

    Loads the job manifest, resolves config, builds runtime, and runs the
    controller. Writes an error signpost to stderr and exits nonzero on failure.

    load_reader_job is added in the subprocess integration subtask; this call
    will raise ImportError until that subtask is complete.
    """
    try:
        from tools.read._reader_job import load_reader_job  # noqa: F401 — added in subtask 5
    except ImportError:
        print("[reader] load_reader_job not yet implemented", file=sys.stderr)
        sys.exit(1)

    try:
        job = load_reader_job(args.reader_job)  # type: ignore[name-defined]
    except Exception as exc:
        print(f"[reader] Failed to load job: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        _run_with_job(job, args)
    except ReaderCancelledError as exc:
        print(f"[reader] Cancelled: {exc}", file=sys.stderr)
        sys.exit(2)
    except ReaderCapacityError as exc:
        print(f"[reader] Capacity error: {exc}", file=sys.stderr)
        sys.exit(3)
    except Exception as exc:
        print(f"[reader] Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)


def _run_with_job(job: ReaderJob, args: Any) -> None:
    """Resolve config and runtime, then run the controller."""
    from agent.config_loader import resolve_model_config
    config = resolve_model_config(job.selection.path.parent)
    runtime = _build_runtime(config, job)
    controller = ReaderController(job=job, config=config, runtime=runtime)
    controller.run()


def _build_runtime(config: "AgentConfig", job: ReaderJob) -> ReaderRuntime:
    """Build a ReaderRuntime from the resolved config."""
    from agent._model_switch import build_openai_client
    client, script_rk = build_openai_client(config)
    request_options = dict(config.request_kwargs)
    if script_rk:
        request_options.update(script_rk)
    return ReaderRuntime(
        client=client,
        model=config.model,
        system_prompt=config.system_prompt,
        request_options=request_options,
        api_error_retries=config.api_error_retries,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk_token_budget(limits: ReaderLimits) -> int:
    """Derive initial chunk token target K = min(R, C-O-M)."""
    K = min(
        limits.output_reserve,
        limits.context_window - limits.output_reserve - limits.estimator_margin,
    )
    if K <= 0:
        raise ReaderCapacityError(
            required_tokens=1,
            available_tokens=K,
            recommendation=ReaderCapacityError.LARGER_MODEL,
        )
    return K


def _first_line(chunk: ReaderChunk) -> int:
    if chunk.references:
        return chunk.references[0].line_start
    return 1


def _last_line(chunk: ReaderChunk) -> int:
    if chunk.references:
        return chunk.references[-1].line_start
    return 1


def _chunk_ref_line(chunk: ReaderChunk) -> str:
    return f"§{chunk.index + 1} lines {_first_line(chunk)}–{_last_line(chunk)}"
