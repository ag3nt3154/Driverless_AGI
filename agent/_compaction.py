"""agent/_compaction.py — context compaction.

Extracted verbatim from AgentLoop methods in agent/loop.py (instance state
became explicit `loop` / `log` parameters) so the loop orchestrator stays
under the 500-line cap. Only agent/loop.py imports from this module.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from agent import session_events as sev
from agent.session_log import InvariantError
from tools.compact._tail_boundary import compute_tail_boundary
from tools.subagent_api import build_fork_context, run_subagent

if TYPE_CHECKING:
    from agent._loop_config import CompactionResult
    from agent.loop import AgentLoop
    from agent.session_log import SessionLog


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


def compact(loop: AgentLoop, force: bool = False) -> "CompactionResult":
    """Compact context via a subprocess that inherits the parent's prefix.

    The compact subprocess receives the parent's warm KV-cache prefix
    through a fork-context file, makes a single non-streaming API call,
    and returns the summary as its handoff. The parent surface is only
    mutated after validating the handoff against the recorded surface
    generation (atomic acceptance).

    Exceptions propagate — callers that want them swallowed use
    compact_context.
    """
    if loop._last_request_snapshot is None:
        from agent._loop_config import _NO_COMPACTION

        return _NO_COMPACTION

    steps = collect_steps(loop.log)
    if not steps:
        from agent._loop_config import _NO_COMPACTION

        return _NO_COMPACTION

    boundary = compute_tail_boundary(
        steps=steps,
        prompt_tokens=loop._last_prompt_tokens,
        keep_recent_tokens=loop.config.keep_recent_tokens,
    )
    if not boundary.has_middle:
        from agent._loop_config import _NO_COMPACTION

        return _NO_COMPACTION

    # --- Resolve structural values from the log ---
    middle_last = boundary.middle_steps[-1]
    step_end_seq: int | None = None
    for evt in loop.log.events:
        if (
            evt.type == sev.STEP_END
            and evt.branch == "main"
            and evt.data.get("turn") == middle_last[0]
            and evt.data.get("step") == middle_last[1]
        ):
            step_end_seq = evt.seq
            break
    if step_end_seq is None:
        from agent._loop_config import _NO_COMPACTION

        return _NO_COMPACTION  # last summarized step incomplete

    nodes = loop.log.surface.nodes
    tail_first = boundary.tail_steps[0]
    try:
        tail_idx = find_surface_index_for_step(loop.log, tail_first)
    except ValueError:
        from agent._loop_config import _NO_COMPACTION

        return _NO_COMPACTION
    if tail_idx == 0:
        from agent._loop_config import _NO_COMPACTION

        return _NO_COMPACTION  # nothing to shadow

    first_summarized_seq = nodes[0]
    last_summarized_seq = nodes[tail_idx - 1]
    pre_gen = loop.log.surface.generation

    # --- Record retroactive BRANCH_START ---
    from uuid import uuid4

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

    # --- Reconstruct the inherited prefix ---
    from agent.context_spec import reconstruct, spec_for_branch

    spec = spec_for_branch(loop.log, branch_id)
    _header, prefix_msgs = reconstruct(loop.log, spec)

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
        result = run_subagent(
            task="",
            preset="compact",
            project_path=loop.config.project_path,
            parent_log=None,
            fork_context_path=fc_path,
        )
    finally:
        Path(fc_path).unlink(missing_ok=True)

    # --- Validate and atomically accept ---
    if not result.is_ok or not result.handoff_text.strip():
        from agent._loop_config import _NO_COMPACTION

        return _NO_COMPACTION
    if loop.log.surface.generation != pre_gen:
        from agent._loop_config import _NO_COMPACTION

        return _NO_COMPACTION  # surface changed during compact

    current_nodes = loop.log.surface.nodes
    if (
        first_summarized_seq not in current_nodes
        or last_summarized_seq not in current_nodes
    ):
        from agent._loop_config import _NO_COMPACTION

        return _NO_COMPACTION  # replacement edges no longer live

    loop._compaction_generation += 1
    summary_content = (
        f"[CONTEXT SUMMARY — conversation compacted "
        f"(generation {loop._compaction_generation})]\n\n"
        f"{result.handoff_text}"
    )
    removed_count = len(boundary.middle_steps)
    source_nodes = list(current_nodes[:tail_idx])
    loop.log.append(
        sev.CONTEXT_COMPACTION,
        {
            "summary": summary_content,
            "removed": removed_count,
            "generation": loop._compaction_generation,
            "branch": branch_id,
            "handoff": str(result.handoff_path),
        },
        surface_op=("replace", first_summarized_seq, last_summarized_seq),
        source_seqs=source_nodes,
    )
    loop._sync_messages()

    from agent._loop_config import CompactionResult

    compaction = CompactionResult(
        did_compact=True,
        generation=loop._compaction_generation,
        summary_content=summary_content,
        removed_count=removed_count,
    )
    loop.callbacks.on_compaction(len(boundary.tail_steps), removed_count)
    return compaction


def compact_context(loop: AgentLoop) -> "CompactionResult":
    """Delegates to compact(). Failures are non-fatal — the session continues
    with un-compacted messages rather than crashing."""
    from agent._loop_config import _NO_COMPACTION

    try:
        return compact(loop)
    except Exception as exc:
        loop.callbacks.on_assistant_text(
            f"[Warning: context compaction failed — {exc}. Continuing with full context.]"
        )
        return _NO_COMPACTION
