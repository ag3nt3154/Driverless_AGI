"""agent/context_spec.py — Context reconstruction from session log + coordinate spec.

A ContextSpec describes a path through the session log tree: one or more
branch segments, each selecting specific (turn, [steps]) pairs. Given a
SessionLog and a ContextSpec, ``reconstruct`` produces the byte-identical
message list that an agent would send to the LLM provider.

The first segment must be ``"main"``. Subsequent segments name branches
whose parent prefix is included by the preceding segments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from agent import session_events as ev
from agent.session_log import SessionEvent, SessionLog
from agent.session_surface import project_event


@dataclass(frozen=True, slots=True)
class BranchSegment:
    """One segment of a context path.

    ``turns`` is a list of ``(turn_number, [step_numbers])`` pairs.
    Step numbers select which steps' surface events are included.
    Step 0 means pre-step surface events (user messages logged before
    the first step/start in that turn).
    """
    branch: str
    turns: list[tuple[int, list[int]]]


@dataclass(frozen=True, slots=True)
class ContextSpec:
    """Path from root to the current agent's position in the log tree."""
    segments: list[BranchSegment]


def _collect_surface_events(
    log: SessionLog,
    branch: str,
    turns: list[tuple[int, list[int]]],
    fork_seq: int | None,
) -> list[SessionEvent]:
    """Collect surface events matching the branch/turn/step filter.

    For the main branch feeding into a subagent, ``fork_seq`` limits which
    events are included: only events with ``seq <= fork_seq`` are considered,
    so events logged after the branch point (like the handoff tool_result)
    are excluded from the subagent's parent prefix.
    """
    turn_steps: dict[int, set[int]] = {t: set(steps) for t, steps in turns}
    result: list[SessionEvent] = []
    for event in log.events:
        if event.branch != branch:
            continue
        if event.surface_op is None:
            continue
        if fork_seq is not None and event.seq > fork_seq:
            continue
        e_turn = event.data.get("turn")
        e_step = event.data.get("step")
        if e_turn not in turn_steps:
            continue
        allowed_steps = turn_steps[e_turn]
        if e_step not in allowed_steps:
            continue
        result.append(event)
    return result


def reconstruct(
    log: SessionLog,
    spec: ContextSpec,
) -> tuple[dict, list[dict]]:
    """Reconstruct the message list from a session log and context spec.

    Returns ``(system_header_msg, conversation_messages)``. The system
    header is the ``{"role": "system", "content": ...}`` envelope; the
    conversation messages are the surface projection in order.

    The caller appends the ephemeral board (if any) after the returned
    messages to form the complete API request.
    """
    if not spec.segments or spec.segments[0].branch != "main":
        raise ValueError(
            "ContextSpec must start with a 'main' segment; "
            f"got {repr(spec.segments[0].branch) if spec.segments else '(empty)'}"
        )

    header_data = log.latest_header()
    if header_data is None:
        raise ValueError("session log has no request/header event")
    system_msg = {"role": "system", "content": header_data["system"]}

    all_surface_events: list[SessionEvent] = []
    for i, segment in enumerate(spec.segments):
        # For non-final segments, limit to events at or before the fork point
        # of the NEXT segment's branch, so post-fork events (e.g. handoff
        # tool_result) are excluded from the subagent's parent prefix.
        fork_seq: int | None = None
        if i < len(spec.segments) - 1:
            next_branch = spec.segments[i + 1].branch
            for evt in log.events:
                if (
                    evt.type == ev.BRANCH_START
                    and evt.data.get("branch") == next_branch
                ):
                    fork_seq = evt.seq
                    break

        events = _collect_surface_events(
            log, segment.branch, segment.turns, fork_seq,
        )
        all_surface_events.extend(events)

    messages = [project_event(e) for e in all_surface_events]
    return system_msg, messages
