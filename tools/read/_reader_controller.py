"""tools/read/_reader_controller.py — Sequential reader controller.

Fixed read loop inside the reader subprocess (no agent loop, no tools):

1. For each chunk, one call with: running summary + chunk (with line numbers).
   The reply has <notes> (section entries for this chunk, appended to a list
   and never rewritten) and <summary> (the running summary, capped at
   SUMMARY_CHARS, used only as context for the next chunk). Context per call
   is constant, so file length is unlimited.
2. Merge all notes into the final index. Notes too big for one call are merged
   in batches first, repeatedly, until one call fits.
3. Flag excerpts that are not found verbatim in the source, check the result
   fits the parent (condensing if not), and write the handoff.

Entry point for the subprocess: run_reader_job_mode(args) is called from
tools/subagent_main.py.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tools.read._budgets import (
    ReaderCapacityError,
    ReaderLimits,
    chunk_token_budget,
    estimate_reader_request,
    estimate_reader_text,
    require_parent_fit,
    resolve_reader_limits,
)
from tools.read._chunking import ReaderChunk, chunk_selection
from tools.read._reader_job import ReaderJob
from tools.read._reader_provider import (
    ReaderRuntime,
    ReaderCancelledError,
    ReaderProviderError,
    build_reader_request,
    call_reader,
    emit_reader_progress,
)

if TYPE_CHECKING:
    from agent._loop_config import AgentCallbacks, AgentConfig


PRESET = "read-large-file"
SUMMARY_CHARS = 6000
_MAX_MERGE_LEVELS = 6

_NOTES_RE = re.compile(r"<notes>(.*?)(?:</notes>|$)", re.DOTALL)
_SUMMARY_RE = re.compile(r"<summary>(.*?)(?:</summary>|$)", re.DOTALL)
# > "verbatim text" (line 12)   or   > "text" (lines 12–14)
_EXCERPT_RE = re.compile(r'^(\s*>\s*)"(.+)"(\s*\(lines?\s[^)]*\))?\s*$')
_NOT_FOUND = " ⚠ not found verbatim in source"


# ---------------------------------------------------------------------------
# Mutable controller state
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChunkNotes:
    """Committed notes for one chunk."""
    index: int
    first_line: int
    last_line: int
    notes: str


@dataclass
class ReaderState:
    """All mutable accumulation owned by the controller.

    chunks   Ordered, immutable chunk sequence for this invocation.
    cursor   Index of the next chunk to read (0 = none read yet).
    summary  Running summary carried into the next chunk's call.
    notes    Per-chunk notes, append-only, in chunk order.
    """
    chunks: tuple[ReaderChunk, ...] = field(default_factory=tuple)
    cursor: int = 0
    summary: str = ""
    notes: list[ChunkNotes] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class ReaderController:
    """Sequential reader for one ReaderJob.

    Never emits a successful handoff on incomplete coverage. Raises on any
    unrecoverable error so the caller can emit a clear failure event.
    """

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
        """Full lifecycle: chunk, read every chunk, merge, verify, hand off."""
        limits = resolve_reader_limits(
            self._job.parent_reserve,
            self._config,
            request_kwargs=self._runtime.request_options,
        )

        fixed = self._fixed_request_tokens(limits)
        self._state.chunks = chunk_selection(
            self._job.selection,
            chunk_tokens=chunk_token_budget(limits, fixed_tokens=fixed),
        )
        if not self._state.chunks:
            raise RuntimeError("chunk_selection returned no chunks for non-empty selection")

        total = len(self._state.chunks)
        for i in range(total):
            emit_reader_progress(
                self._runtime.callbacks, completed=i, total=total, phase="reading",
            )
            self._read_next(limits)

        if self._state.cursor != total:
            raise RuntimeError(
                f"Coverage incomplete: read {self._state.cursor} of {total} chunks"
            )

        emit_reader_progress(
            self._runtime.callbacks, completed=total, total=total, phase="merging",
        )
        index = self._merge(limits)
        index = flag_unverified_excerpts(index, self._job.selection.text)
        content = self._fit_parent(self._compose(index), limits)
        self._write_handoff(content)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def _chunk_message(self, chunk: ReaderChunk | None, summary: str) -> dict:
        sel = self._job.selection
        total = len(self._state.chunks) or 1
        if chunk is None:
            # Sizing probe: no chunk text, summary at its cap.
            position, body = "?/?", ""
        else:
            position = f"{chunk.index + 1}/{total}"
            body = render_chunk(chunk)
        query = self._job.query or "none — produce a general digest"
        return {
            "role": "user",
            "content": (
                f"File: {sel.path.name} ({sel.scope})\n"
                f"Focus query: {query}\n\n"
                f"Running summary so far:\n{summary or '(this is the first chunk)'}\n\n"
                f"Source chunk {position}"
                + (f" — lines {first_line(chunk)}–{last_line(chunk)}" if chunk else "")
                + f":\n{body}\n\n"
                f"Reply with <notes>…</notes> for this chunk, then "
                f"<summary>…</summary> (under {SUMMARY_CHARS} characters)."
            ),
        }

    def _fixed_request_tokens(self, limits: ReaderLimits) -> int:
        probe = self._chunk_message(None, "x" * SUMMARY_CHARS)
        req = build_reader_request(
            [probe], runtime=self._runtime, output_tokens=limits.output_reserve,
        )
        return estimate_reader_request(req)

    def _read_next(self, limits: ReaderLimits) -> None:
        """Read one chunk, commit its notes, advance the summary."""
        chunk = self._state.chunks[self._state.cursor]
        req = build_reader_request(
            [self._chunk_message(chunk, self._state.summary)],
            runtime=self._runtime,
            output_tokens=limits.output_reserve,
        )
        reply = call_reader(req, runtime=self._runtime, limits=limits)
        parsed = parse_chunk_reply(reply)
        if parsed is None:
            reply = call_reader(req, runtime=self._runtime, limits=limits)
            parsed = parse_chunk_reply(reply)
        if parsed is None:
            # Still unparseable: keep the reply as this chunk's notes and the
            # previous summary, so coverage is preserved.
            parsed = (reply.strip(), self._state.summary)

        notes, summary = parsed
        self._commit(chunk, notes, summary)

    def _commit(self, chunk: ReaderChunk, notes: str, summary: str) -> None:
        if chunk.index != self._state.cursor:
            raise RuntimeError(
                f"Out-of-order commit: expected cursor {self._state.cursor}, "
                f"got chunk_index {chunk.index}"
            )
        self._state.notes.append(ChunkNotes(
            index=chunk.index,
            first_line=first_line(chunk),
            last_line=last_line(chunk),
            notes=notes,
        ))
        self._state.summary = summary[:SUMMARY_CHARS]
        self._state.cursor += 1

    # ------------------------------------------------------------------
    # Merging
    # ------------------------------------------------------------------

    def _target_tokens(self, limits: ReaderLimits) -> int:
        """Output size for the final index: half the parent's reserve."""
        return max(256, min(limits.output_reserve, self._job.parent_reserve // 2))

    def _merge_request(self, blocks: list[str], *, final: bool, out_tokens: int) -> dict:
        sel = self._job.selection
        query = self._job.query or "none — general digest"
        if final:
            instruction = (
                "Write the final index of the file from the section notes below.\n"
                f"Focus query: {query}\n"
                f"Stay under {out_tokens * 4} characters. Use exactly this format:\n\n"
                "## Overview\n3–5 sentences on what the file is and how it is organised.\n\n"
                "## Index\n| Lines | Section | Contents |\n|---|---|---|\n"
                "| a–b | title | one line |\n\n"
                "## Sections\n### §1 Title (lines a–b)\n- key point\n"
                '> "verbatim excerpt" (line n)\n\n'
                "Keep line ranges exact and excerpts copied verbatim from the notes; "
                "never invent quotes. Merge adjacent notes that belong to the same "
                "section. Start directly with \"## Overview\"."
            )
        else:
            instruction = (
                "Condense the section notes below into fewer, tighter section notes "
                "in the same format (### Title (lines a–b), bullet points, "
                '> "verbatim excerpt" (line n)). Keep line ranges exact and excerpts '
                f"verbatim; drop minor points first. Focus query: {query}. "
                f"Stay under {out_tokens * 4} characters."
            )
        msg = {
            "role": "user",
            "content": f"File: {sel.path.name} ({sel.scope})\n\n{instruction}\n\n"
                       + "\n\n".join(blocks),
        }
        return build_reader_request([msg], runtime=self._runtime, output_tokens=out_tokens)

    def _fits(self, req: dict, limits: ReaderLimits) -> bool:
        return (
            estimate_reader_request(req) + limits.output_reserve + limits.estimator_margin
            <= limits.context_window
        )

    def _merge(self, limits: ReaderLimits) -> str:
        """Merge all chunk notes into one index, batching when needed."""
        target = self._target_tokens(limits)
        blocks = [
            f"#### Notes for lines {n.first_line}–{n.last_line}\n{n.notes}"
            for n in self._state.notes
        ]
        for _ in range(_MAX_MERGE_LEVELS):
            final_req = self._merge_request(blocks, final=True, out_tokens=target)
            if self._fits(final_req, limits):
                return call_reader(final_req, runtime=self._runtime, limits=limits).strip()
            batches = self._batch(blocks, limits, target)
            blocks = [
                call_reader(
                    self._merge_request(batch, final=False, out_tokens=target),
                    runtime=self._runtime, limits=limits,
                ).strip()
                for batch in batches
            ]
        raise ReaderCapacityError(
            required_tokens=sum(estimate_reader_text(b) for b in blocks),
            available_tokens=limits.context_window,
            recommendation=ReaderCapacityError.NARROW_RANGE,
        )

    def _batch(self, blocks: list[str], limits: ReaderLimits, target: int) -> list[list[str]]:
        """Greedy groups of consecutive blocks whose merge request fits C."""
        batches: list[list[str]] = []
        current: list[str] = []
        for block in blocks:
            trial = current + [block]
            if current and not self._fits(
                self._merge_request(trial, final=False, out_tokens=target), limits
            ):
                batches.append(current)
                current = [block]
            else:
                current = trial
        if current:
            batches.append(current)
        if len(batches) == len(blocks) and len(blocks) > 1:
            # Pairs at minimum, so every level halves the block count.
            batches = [blocks[i:i + 2] for i in range(0, len(blocks), 2)]
        return batches

    # ------------------------------------------------------------------
    # Finalizing
    # ------------------------------------------------------------------

    def _compose(self, index: str) -> str:
        sel = self._job.selection
        title = f"# {sel.path.name} — {sel.scope}, ~{estimate_reader_text(sel.text):,} tokens"
        if self._job.query:
            title += f"\nQuery: {self._job.query}"
        return f"{self._job.return_format.signpost}\n\n{title}\n\n{index}"

    def _fit_parent(self, content: str, limits: ReaderLimits) -> str:
        """Return content if it fits the parent, else condense it (bounded)."""
        try:
            require_parent_fit(content, self._job.parent_reserve)
            return content
        except ReaderCapacityError:
            pass

        target_chars = self._job.parent_reserve * 4 // 2
        for _ in range(max(1, self._config.max_continuations)):
            msg = {
                "role": "user",
                "content": (
                    f"Shorten this index to under {target_chars} characters. Keep the "
                    "Overview, the Index table and every section heading with its line "
                    "range; drop lesser points and excerpts first. Do not add content.\n\n"
                    + content
                ),
            }
            req = build_reader_request(
                [msg], runtime=self._runtime,
                output_tokens=min(target_chars // 4 + 1, limits.output_reserve),
            )
            try:
                shorter = call_reader(req, runtime=self._runtime, limits=limits).strip()
            except (ReaderProviderError, ReaderCapacityError):
                break
            if len(shorter) >= len(content):
                break  # no progress
            content = shorter
            try:
                require_parent_fit(content, self._job.parent_reserve)
                return content
            except ReaderCapacityError:
                continue

        raise ReaderCapacityError(
            required_tokens=len(content) // 4,
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
# Pure helpers
# ---------------------------------------------------------------------------

def first_line(chunk: ReaderChunk) -> int:
    return chunk.references[0].line_start if chunk.references else 1


def last_line(chunk: ReaderChunk) -> int:
    """Line number of the chunk's last line (not the last reference's start)."""
    if not chunk.references:
        return 1 + chunk.text.rstrip("\n").count("\n")
    ref = chunk.references[-1]
    span_text = chunk.text[ref.start:ref.end].rstrip("\n")
    return ref.line_start + span_text.count("\n")


def render_chunk(chunk: ReaderChunk) -> str:
    """Chunk text with cat-n line numbers, so notes can cite exact lines."""
    start = first_line(chunk)
    lines = chunk.text.rstrip("\n").split("\n")
    return "\n".join(f"{start + i:6d}\t{line}" for i, line in enumerate(lines))


def parse_chunk_reply(reply: str) -> tuple[str, str] | None:
    """Split a reply into (notes, summary); None if <notes> is missing."""
    notes_m = _NOTES_RE.search(reply)
    if notes_m is None or not notes_m.group(1).strip():
        return None
    summary_m = _SUMMARY_RE.search(reply)
    summary = summary_m.group(1).strip() if summary_m else ""
    return notes_m.group(1).strip(), summary


def _normalise(text: str) -> str:
    return " ".join(text.split())


def flag_unverified_excerpts(index: str, source_text: str) -> str:
    """Append a warning to every quoted excerpt not found verbatim in the source.

    Whitespace is normalised and an ellipsis inside a quote splits it into
    pieces that are each checked.
    """
    source = _normalise(source_text)
    out: list[str] = []
    for line in index.split("\n"):
        m = _EXCERPT_RE.match(line)
        if m:
            quote = m.group(2).replace('\\"', '"')  # models often escape inner quotes
            pieces = [p for p in re.split(r"…|\.\.\.", quote) if _normalise(p)]
            if pieces and not all(_normalise(p) in source for p in pieces):
                line += _NOT_FOUND
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Subprocess entry point
# ---------------------------------------------------------------------------

def run_reader_job_mode(args: Any) -> None:
    """Entry point called from tools/subagent_main.py when --reader-job is set.

    Loads the job manifest, resolves config, builds runtime, and runs the
    controller. Writes an error to stderr and exits nonzero on failure.
    """
    from tools.read._reader_job import load_reader_job

    try:
        job = load_reader_job(Path(args.reader_job))
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


def _reader_config(args: Any) -> "AgentConfig":
    """Resolve the project's config at the preset's model tier (worker by default)."""
    from agent.config_loader import resolve_model_config
    from tools.subagent_main import _apply_advanced_config, _apply_worker_config

    project = Path(args.project).resolve() if getattr(args, "project", None) else Path.cwd()
    base = resolve_model_config(getattr(args, "model", None), project_path=project)
    tier = getattr(args, "model_tier", None) or "worker"
    if tier == "worker":
        return _apply_worker_config(base)
    if tier == "advanced":
        return _apply_advanced_config(base)
    return base


def _run_with_job(job: ReaderJob, args: Any) -> None:
    """Resolve config and runtime, then run the controller."""
    config = _reader_config(args)
    runtime = _build_runtime(config, job)
    ReaderController(job=job, config=config, runtime=runtime).run()


def load_reader_prompt(project_path: Path) -> str:
    """The preset's prompt.md (project override first, then DAGI root)."""
    from agent import DAGI_ROOT
    for root in (project_path, DAGI_ROOT):
        p = root / ".dagi" / "subagents" / PRESET / "prompt.md"
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return ""


def _build_pipe_callbacks() -> "AgentCallbacks":
    """Minimal callbacks that emit newline-delimited JSON to stdout."""
    import json as _json
    from agent.loop import AgentCallbacks

    def _emit(evt: dict) -> None:
        print(_json.dumps(evt), flush=True)

    return AgentCallbacks(
        on_assistant_text=lambda text: (
            _emit({"type": "message", "content": text}) if text.strip() else None
        ),
        on_error=lambda e: _emit({"type": "error", "message": str(e)}),
    )


def _build_runtime(config: "AgentConfig", job: ReaderJob) -> ReaderRuntime:
    """Build a ReaderRuntime from the resolved config."""
    from agent._model_switch import build_openai_client
    from tools.write_handoff._write_handoff import WriteHandoffTool
    client, script_rk = build_openai_client(config)
    request_options = dict(config.request_kwargs)
    if script_rk:
        request_options.update(script_rk)
    return ReaderRuntime(
        client=client,
        model=config.model,
        system_prompt=load_reader_prompt(Path(config.project_path)),
        request_options=request_options,
        api_error_retries=config.api_error_retries,
        callbacks=_build_pipe_callbacks(),
        handoff_tool=WriteHandoffTool(handoff_path=job.return_format.handoff_path),
    )
