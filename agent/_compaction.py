"""Context selection, default-model summarization, and atomic history replacement.

Failed summarization removes the selected prefix from active context while
retaining the raw session log. AgentLoop delegates compaction to this module.
"""
from __future__ import annotations

import json
import os
import tempfile
from itertools import takewhile
from pathlib import Path
from typing import TYPE_CHECKING

from agent import session_events as sev
from agent.session_log import InvariantError
from tools.compact._tail_boundary import (
    TailBoundary,
    compute_tail_boundary,
    estimate_tokens,
)
from tools.subagent_api import build_fork_context, run_subagent

if TYPE_CHECKING:
    from agent._loop_config import CompactionResult
    from agent.loop import AgentLoop
    from agent.session_log import SessionLog


def compute_step_sizes(
    log: SessionLog,
    steps: list[tuple[int, int]],
) -> list[int]:
    """Estimate token count per step from surface events."""
    step_set = {s for s in steps}
    sizes: dict[tuple[int, int], int] = {s: 0 for s in steps}
    event_map = {e.seq: e for e in log.events}
    for seq in log.surface.nodes:
        event = event_map.get(seq)
        if event is None:
            continue
        key = (event.data.get("turn"), event.data.get("step"))
        if key not in step_set:
            continue
        msg = event.data.get("message")
        if msg:
            sizes[key] += estimate_tokens(msg)
        content = event.data.get("content")
        if content and not msg:
            sizes[key] += max(len(str(content)) // 4, 1)
    return [sizes[s] for s in steps]


def collect_steps(log: SessionLog) -> list[tuple[int, int]]:
    """Return chronological (turn, step) pairs that are active on the surface."""
    event_map = {e.seq: e for e in log.events}
    steps: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for seq in log.surface.nodes:
        event = event_map.get(seq)
        if event is None:
            continue
        t = event.data.get("turn")
        s = event.data.get("step")
        if t is not None and s is not None:
            key = (t, s)
            if key not in seen:
                seen.add(key)
                steps.append(key)
    return steps


def find_surface_index_for_step(log: SessionLog, target: tuple[int, int]) -> int:
    """Return the surface node index of the first event in the given (turn, step)."""
    t_turn, t_step = target
    event_map = {e.seq: e for e in log.events}
    for idx, seq in enumerate(log.surface.nodes):
        event = event_map.get(seq)
        if event is None:
            continue
        if event.data.get("turn") == t_turn and event.data.get("step") == t_step:
            return idx
    raise ValueError(f"step ({t_turn}, {t_step}) not found on surface")


def log_compaction(
    log: SessionLog,
    result: "CompactionResult",
    tail_first_step: tuple[int, int],
    sync_fn,
) -> None:
    """Record a subagent compaction as a surface replace.

    Shadows all surface nodes before the tail's first step with a single
    CONTEXT_COMPACTION event containing the summary.
    """
    if not result.did_compact:
        return
    nodes = log.surface.nodes
    if not nodes:
        return

    try:
        tail_surface_idx = find_surface_index_for_step(log, tail_first_step)
    except ValueError:
        raise InvariantError(
            f"tail step {tail_first_step} not found on surface — "
            f"cannot log compaction"
        )

    lo = 0
    hi = tail_surface_idx - 1

    if hi < lo:
        return  # nothing to shadow (tail starts at position 0)
    if hi >= len(nodes):
        raise InvariantError(
            f"compaction span [{lo}, {hi}] is outside surface of "
            f"{len(nodes)} node(s)"
        )

    log.append(
        sev.CONTEXT_COMPACTION,
        {
            "summary": result.summary_content,
            "removed": result.removed_count,
            "generation": result.generation,
        },
        surface_op=("replace", nodes[lo], nodes[hi]),
        source_seqs=nodes[lo:hi + 1],
    )
    sync_fn()


def _select_compaction(
    loop: AgentLoop, summarize_all: bool,
) -> tuple[TailBoundary, int, tuple[int, ...]] | None:
    """Select a complete prefix and retain its exact source nodes before starting work."""
    if loop._last_request_snapshot is None:
        return None

    steps = collect_steps(loop.log)
    # Step-zero entries (seeds, user messages) lack STEP_END markers and
    # are never valid compaction cut points — exclude them.
    steps = [(t, s) for t, s in steps if s != 0]
    if not steps:
        return None

    if summarize_all:
        boundary = TailBoundary(
            tail_start_index=len(steps),
            keep_count=0,
            tail_steps=[],
            middle_steps=list(steps),
        )
    else:
        step_sizes = compute_step_sizes(loop.log, steps)
        boundary = compute_tail_boundary(
            steps=steps,
            prompt_tokens=loop._last_prompt_tokens,
            keep_recent_tokens=loop.config.keep_recent_tokens,
            step_sizes=step_sizes,
        )
        if not boundary.has_middle:
            return None

    step_end_seq = _completed_step_end(loop.log, boundary.middle_steps[-1])
    source_nodes = _selected_source_nodes(loop.log, boundary, step_end_seq)
    if step_end_seq is None or not source_nodes:
        return None
    return boundary, step_end_seq, source_nodes


def _completed_step_end(log: SessionLog, step: tuple[int, int]) -> int | None:
    """Only completed main-branch steps may end the selected prefix."""
    for event in log.events:
        if (event.type == sev.STEP_END and event.branch == "main"
                and (event.data.get("turn"), event.data.get("step")) == step):
            return event.seq
    return None


def _selected_source_nodes(
    log: SessionLog, boundary: TailBoundary, step_end_seq: int | None,
) -> tuple[int, ...]:
    """Freeze the exact prefix before the retained tail.

    With no tail (recovery's summarize_all), stop at the worker's cut: nodes
    after ``step_end_seq`` — the open turn's prompt — were never summarised,
    so they must stay verbatim rather than be replaced.
    """
    if not boundary.tail_steps:
        if step_end_seq is None:
            return ()
        return tuple(takewhile(lambda seq: seq <= step_end_seq, log.surface.nodes))
    try:
        tail_idx = find_surface_index_for_step(log, boundary.tail_steps[0])
    except ValueError:
        return ()
    return tuple(log.surface.nodes[:tail_idx])


def _run_compact_worker(loop: AgentLoop, branch_id: str, step_end_seq: int, pre_gen: int):
    """Prepare the selected history and ask the default-model worker for a summary."""
    # --- Reconstruct the inherited prefix ---
    from agent.context_spec import reconstruct, spec_for_branch

    spec = spec_for_branch(loop.log, branch_id)
    _header, prefix_msgs = reconstruct(loop.log, spec)

    # Materialize dagi_image references into inline data URLs — the compaction
    # subprocess only ever sees an actual provider request snapshot, never
    # internal asset-store references.
    from agent.image_assets import materialize_messages, ImageAssetStore

    store = ImageAssetStore(loop.config.project_path)
    prefix_msgs = materialize_messages(list(prefix_msgs), store)

    fork_messages = [
        {"role": "system", "content": _header["content"]},
        *prefix_msgs,
    ]
    fork_snapshot = {**loop._last_request_snapshot, "messages": fork_messages}
    fork_ctx = build_fork_context(
        branch_id=branch_id,
        parent_cut_seq=step_end_seq,
        parent_surface_generation=pre_gen,
        request_snapshot=fork_snapshot,
    )

    # --- Write fork-context and run subprocess ---
    fd, fc_path = tempfile.mkstemp(suffix=".json", prefix="dagi_fork_ctx_")
    os.close(fd)
    try:
        Path(fc_path).write_text(json.dumps(fork_ctx), encoding="utf-8")
        return run_subagent(
            task="",
            preset="compact",
            project_path=loop.config.project_path,
            parent_log=None,
            fork_context_path=fc_path,
        )
    finally:
        Path(fc_path).unlink(missing_ok=True)


def _summarize_selection(
    loop: AgentLoop, branch_id: str, step_end_seq: int, pre_gen: int,
) -> tuple[str, str | None, str]:
    """Convert worker/preparation failures into fallback reasons before touching history."""
    try:
        result = _run_compact_worker(loop, branch_id, step_end_seq, pre_gen)
        if result.is_ok and result.handoff_text.strip():
            return result.handoff_text, str(result.handoff_path), ""
        reason = result.message or (
            "worker returned an empty summary" if result.is_ok else f"worker status: {result.status}"
        )
        details = f" Details: {result.output_log_path}." if result.output_log_path else ""
        return "", None, f"{reason}.{details}"
    except Exception as exc:
        return "", None, f"{type(exc).__name__}: {exc}"


def compact(loop: AgentLoop, force: bool = False, summarize_all: bool = False) -> "CompactionResult":
    """Replace a selected prefix with a summary, or an omission notice if the worker fails.

    Both paths preserve raw events and the recent tail. A changed surface rejects
    either replacement so a stale worker cannot discard newer context.
    """
    from uuid import uuid4
    from agent._loop_config import CompactionResult, _NO_COMPACTION

    selection = _select_compaction(loop, summarize_all)
    if selection is None:
        return _NO_COMPACTION
    boundary, step_end_seq, source_nodes = selection
    pre_gen = loop.log.surface.generation
    middle_last = boundary.middle_steps[-1]
    branch_id = f"compact_{uuid4().hex[:8]}"
    loop.log.append(
        sev.BRANCH_START,
        {
            "branch": branch_id,
            "parent_branch": "main",
            "turn": middle_last[0],
            "step": middle_last[1],
            "parent_cut_seq": step_end_seq,
            "parent_surface_generation": pre_gen,
        },
    )
    summary, handoff, failure = _summarize_selection(loop, branch_id, step_end_seq, pre_gen)

    if (loop.log.surface.generation != pre_gen
            or tuple(loop.log.surface.nodes[:len(source_nodes)]) != source_nodes):
        return _NO_COMPACTION

    generation = loop._compaction_generation + 1
    if failure:
        summary_content = (
            "[CONTEXT REMOVED — earlier history was removed without a summary "
            "because compaction failed. The raw session log retains the original history.]"
        )
    else:
        summary_content = (
            f"[CONTEXT SUMMARY — conversation compacted (generation {generation})]\n\n"
            f"{summary}"
        )
    removed_count = len(boundary.middle_steps)
    loop.log.append(
        sev.CONTEXT_COMPACTION,
        {
            "summary": summary_content,
            "removed": removed_count,
            "generation": generation,
            "branch": branch_id,
            "handoff": handoff,
            "fallback": bool(failure),
            "failure_reason": failure[:1000],
        },
        surface_op=("replace", source_nodes[0], source_nodes[-1]),
        source_seqs=source_nodes,
    )
    loop._compaction_generation = generation
    loop._sync_messages()
    if failure:
        loop.callbacks.on_assistant_text(
            f"[Warning: context compaction failed — {failure[:1000]} "
            f"Selected history chunk removed without a summary ({removed_count} steps).]"
        )
    loop.callbacks.on_compaction(len(boundary.tail_steps), removed_count)
    return CompactionResult(True, generation, summary_content, removed_count)


def compact_context(loop: AgentLoop) -> "CompactionResult":
    """Delegate to compact; report errors outside its validated worker fallback."""
    from agent._loop_config import _NO_COMPACTION

    try:
        return compact(loop)
    except Exception as exc:
        loop.callbacks.on_assistant_text(
            f"[Warning: context compaction failed — {exc}. Continuing with full context.]"
        )
        return _NO_COMPACTION
