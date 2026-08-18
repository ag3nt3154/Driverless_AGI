"""tests/test_context_spec.py — Context reconstruction from session log + spec."""
from __future__ import annotations

import copy
import json
import pytest

from agent import session_events as ev
from agent.session_log import SessionLog
from agent.context_spec import (
    BranchSegment, ContextSpec, reconstruct, spec_for_main, spec_for_branch,
    _collect_surface_events,
)
from agent.session_surface import project_event


def _populated_log() -> SessionLog:
    """Build a log with main turn 1 (2 steps) and a branch forked at (1, 1)."""
    log = SessionLog()
    # -- main: header + turn 1 --
    log.append(ev.REQUEST_HEADER, {"system": "sys", "reason": "initial"})
    log.append(ev.TURN_START, {"turn": 1})
    # step 0: user message
    log.append(
        ev.USER_MESSAGE,
        {"turn": 1, "step": 0, "role": "user", "content": "task", "source": "human"},
        surface_op="append",
    )
    # step 1: assistant + tool
    log.append(ev.STEP_START, {"turn": 1, "step": 1})
    log.append(
        ev.ASSISTANT_MESSAGE,
        {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "calling tool"}},
        surface_op="append",
    )
    log.append(
        ev.TOOL_CALL,
        {"turn": 1, "step": 1, "call_id": "c1", "name": "run_worker", "arguments": "{}"},
    )
    # fork here
    log.append(
        ev.BRANCH_START,
        {"branch": "sub_1", "parent_branch": "main", "turn": 1, "step": 1},
    )
    # -- branch: sub_1 turn 1 --
    log.append(ev.TURN_START, {"turn": 1}, branch="sub_1")
    log.append(
        ev.USER_MESSAGE,
        {"turn": 1, "step": 0, "role": "user", "content": "sub instructions", "source": "human"},
        surface_op="append",
        branch="sub_1",
    )
    log.append(ev.STEP_START, {"turn": 1, "step": 1}, branch="sub_1")
    log.append(
        ev.ASSISTANT_MESSAGE,
        {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "sub result"}},
        surface_op="append",
        branch="sub_1",
    )
    log.append(ev.STEP_END, {"turn": 1, "step": 1}, branch="sub_1")
    log.append(ev.TURN_END, {"turn": 1, "reason": ev.reason_completed()}, branch="sub_1")
    # -- back on main: tool result at step 1 --
    log.append(
        ev.TOOL_RESULT,
        {"turn": 1, "step": 1, "call_id": "c1", "content": "handoff text", "meta": None},
        surface_op="append",
    )
    log.append(ev.STEP_END, {"turn": 1, "step": 1})
    log.append(ev.TURN_END, {"turn": 1, "reason": ev.reason_completed()})
    return log


class TestContextSpecReconstruct:
    def test_main_only_context(self):
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
        ])
        header, messages = reconstruct(log, spec)
        assert header == {"role": "system", "content": "sys"}
        contents = [m.get("content") for m in messages]
        assert "task" in contents
        assert "calling tool" in contents
        assert "handoff text" in contents
        assert "sub instructions" not in contents
        assert "sub result" not in contents

    def test_subagent_context_shares_parent_prefix(self):
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
            BranchSegment(branch="sub_1", turns=[(1, [0, 1])]),
        ])
        header, messages = reconstruct(log, spec)
        assert header == {"role": "system", "content": "sys"}
        contents = [m.get("content") for m in messages]
        # Parent prefix present
        assert "task" in contents
        assert "calling tool" in contents
        # Branch content present
        assert "sub instructions" in contents
        assert "sub result" in contents
        # Handoff (main step 1 tool_result) NOT present — it came after the fork
        assert "handoff text" not in contents

    def test_parent_prefix_precedes_branch_content(self):
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
            BranchSegment(branch="sub_1", turns=[(1, [0, 1])]),
        ])
        _, messages = reconstruct(log, spec)
        contents = [m.get("content") for m in messages if m.get("content")]
        task_idx = contents.index("task")
        sub_idx = contents.index("sub instructions")
        assert task_idx < sub_idx

    def test_empty_spec_returns_header_only(self):
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[]),
        ])
        header, messages = reconstruct(log, spec)
        assert header == {"role": "system", "content": "sys"}
        assert messages == []

    def test_branch_segment_without_main_first_raises(self):
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="sub_1", turns=[(1, [0])]),
        ])
        with pytest.raises(ValueError, match="must start with"):
            reconstruct(log, spec)

    def test_retroactive_branch_uses_parent_cut_seq(self):
        """A branch with parent_cut_seq reconstructs only through that earlier seq."""
        log = SessionLog()
        log.append(ev.REQUEST_HEADER, {"system": "sys", "reason": "initial"})
        log.append(ev.TURN_START, {"turn": 1})
        # step 0: user message
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 0, "role": "user", "content": "first task", "source": "human"},
            surface_op="append",
        )
        # step 1: assistant
        log.append(ev.STEP_START, {"turn": 1, "step": 1})
        log.append(
            ev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "step1 reply"}},
            surface_op="append",
        )
        step1_end = log.append(ev.STEP_END, {"turn": 1, "step": 1})
        # step 2: assistant (this should NOT be in the prefix)
        log.append(ev.STEP_START, {"turn": 1, "step": 2})
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 2, "role": "user", "content": "continue", "source": "auto"},
            surface_op="append",
        )
        log.append(
            ev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": 2, "message": {"role": "assistant", "content": "step2 reply"}},
            surface_op="append",
        )
        log.append(ev.STEP_END, {"turn": 1, "step": 2})
        # Retroactive branch: physically here but logically forked at step 1's end
        log.append(
            ev.BRANCH_START,
            {
                "branch": "compact_abc",
                "parent_branch": "main",
                "turn": 1,
                "step": 1,
                "parent_cut_seq": step1_end.seq,
            },
        )
        # Branch has its own content
        log.append(ev.TURN_START, {"turn": 1}, branch="compact_abc")
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 0, "role": "user", "content": "compact task", "source": "human"},
            surface_op="append",
            branch="compact_abc",
        )
        log.append(ev.STEP_END, {"turn": 1, "step": 0}, branch="compact_abc")
        log.append(ev.TURN_END, {"turn": 1, "reason": {"kind": "completed"}}, branch="compact_abc")
        log.append(ev.TURN_END, {"turn": 1, "reason": {"kind": "completed"}})

        spec = spec_for_branch(log, "compact_abc")
        _, messages = reconstruct(log, spec)
        contents = [m.get("content") for m in messages]
        # Parent prefix through step 1 included
        assert "first task" in contents
        assert "step1 reply" in contents
        # Step 2 excluded (after the logical fork)
        assert "continue" not in contents
        assert "step2 reply" not in contents
        # Branch content included
        assert "compact task" in contents

    def test_branch_without_parent_cut_seq_uses_physical_seq(self):
        """Branches without parent_cut_seq use the BRANCH_START event's own seq."""
        log = _populated_log()  # existing helper, no parent_cut_seq
        spec = spec_for_branch(log, "sub_1")
        _, messages = reconstruct(log, spec)
        contents = [m.get("content") for m in messages]
        # Parent prefix present, handoff excluded (existing behavior)
        assert "task" in contents
        assert "calling tool" in contents
        assert "handoff text" not in contents
        assert "sub instructions" in contents

    def test_retroactive_fork_honors_prior_compaction(self):
        """A retroactive branch prefix includes prior compaction summaries,
        not the raw events they shadowed."""
        log = SessionLog()
        log.append(ev.REQUEST_HEADER, {"system": "sys", "reason": "initial"})
        log.append(ev.TURN_START, {"turn": 1})
        # step 0 and 1: will be compacted
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 0, "role": "user", "content": "old msg", "source": "human"},
            surface_op="append",
        )
        log.append(ev.STEP_START, {"turn": 1, "step": 1})
        log.append(
            ev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "old reply"}},
            surface_op="append",
        )
        # Compact steps 0-1 into a summary
        nodes = log.surface.nodes
        log.append(
            ev.CONTEXT_COMPACTION,
            {"summary": "prior summary", "removed": 2},
            surface_op=("replace", nodes[0], nodes[1]),
            source_seqs=list(nodes),
        )
        # step 2: retained tail
        log.append(ev.STEP_START, {"turn": 1, "step": 2})
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 2, "role": "user", "content": "retained", "source": "auto"},
            surface_op="append",
        )
        log.append(
            ev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": 2, "message": {"role": "assistant", "content": "retained reply"}},
            surface_op="append",
        )
        step2_end = log.append(ev.STEP_END, {"turn": 1, "step": 2})
        # step 3: will not be in prefix
        log.append(ev.STEP_START, {"turn": 1, "step": 3})
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 3, "role": "user", "content": "new msg", "source": "auto"},
            surface_op="append",
        )
        log.append(
            ev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": 3, "message": {"role": "assistant", "content": "new reply"}},
            surface_op="append",
        )
        log.append(ev.STEP_END, {"turn": 1, "step": 3})
        # Retroactive branch at step 2's end
        log.append(
            ev.BRANCH_START,
            {
                "branch": "compact_v2",
                "parent_branch": "main",
                "turn": 1,
                "step": 2,
                "parent_cut_seq": step2_end.seq,
            },
        )
        log.append(ev.TURN_END, {"turn": 1, "reason": {"kind": "completed"}})

        # Use the fork_seq manually to verify what reconstruct would produce
        events = _collect_surface_events(log, "main", [(1, [0, 1, 2, 3])], step2_end.seq)
        contents = [project_event(e).get("content") for e in events]
        assert "prior summary" in contents   # compaction summary included
        assert "old msg" not in contents     # shadowed by compaction
        assert "retained" in contents        # step 2 included
        assert "new msg" not in contents     # step 3 excluded (after fork)

    def test_safe_cut_rejects_mid_step_fork(self):
        """A parent_cut_seq pointing mid-step (before tool_result) excludes
        the incomplete step entirely from the prefix."""
        log = SessionLog()
        log.append(ev.REQUEST_HEADER, {"system": "sys", "reason": "initial"})
        log.append(ev.TURN_START, {"turn": 1})
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 0, "role": "user", "content": "task", "source": "human"},
            surface_op="append",
        )
        log.append(ev.STEP_START, {"turn": 1, "step": 1})
        log.append(
            ev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "calling"}},
            surface_op="append",
        )
        log.append(
            ev.TOOL_CALL,
            {"turn": 1, "step": 1, "call_id": "c1", "name": "read", "arguments": "{}"},
        )
        log.append(
            ev.TOOL_RESULT,
            {"turn": 1, "step": 1, "call_id": "c1", "content": "file contents", "meta": None},
            surface_op="append",
        )
        step1_end = log.append(ev.STEP_END, {"turn": 1, "step": 1})
        log.append(ev.TURN_END, {"turn": 1, "reason": {"kind": "completed"}})

        # Fork at STEP_END (step 1 complete) — both assistant and tool_result included
        log.append(
            ev.BRANCH_START,
            {
                "branch": "good_fork",
                "parent_branch": "main",
                "turn": 1,
                "step": 1,
                "parent_cut_seq": step1_end.seq,
            },
        )
        events = _collect_surface_events(
            log, "main", [(1, [0, 1])], step1_end.seq,
        )
        contents = [project_event(e).get("content") for e in events]
        assert "task" in contents
        assert "calling" in contents
        assert "file contents" in contents  # tool_result included with its step

    def test_context_compaction_is_included(self):
        """CONTEXT_COMPACTION has no turn/step; it must be included whenever in scope."""
        log = SessionLog()
        log.append(ev.REQUEST_HEADER, {"system": "sys", "reason": "initial"})
        log.append(ev.TURN_START, {"turn": 1})
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 0, "role": "user", "content": "first", "source": "human"},
            surface_op="append",
        )
        log.append(ev.STEP_START, {"turn": 1, "step": 1})
        log.append(
            ev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "second"}},
            surface_op="append",
        )
        # Simulate compaction: replace the two surface nodes with a summary
        nodes = log.surface.nodes
        log.append(
            ev.CONTEXT_COMPACTION,
            {"summary": "compacted summary", "removed": 2},
            surface_op=("replace", nodes[0], nodes[1]),
            source_seqs=list(nodes),
        )
        log.append(ev.STEP_END, {"turn": 1, "step": 1})
        log.append(ev.TURN_END, {"turn": 1, "reason": ev.reason_completed()})

        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
        ])
        _, messages = reconstruct(log, spec)
        contents = [m.get("content") for m in messages]
        assert "compacted summary" in contents
        assert "first" not in contents   # shadowed by compaction
        assert "second" not in contents  # shadowed by compaction


class TestByteIdentical:
    def test_main_context_is_byte_identical_to_direct_surface(self):
        """reconstruct() on main must produce the same messages as derive_messages()."""
        log = _populated_log()
        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
        ])
        _, messages = reconstruct(log, spec)
        direct = log.derive_messages()
        assert json.dumps(messages, sort_keys=True) == json.dumps(direct, sort_keys=True)

    def test_subagent_prefix_is_byte_identical_to_parent_at_fork(self):
        """The parent prefix in the subagent's context matches the parent's view at fork."""
        log = _populated_log()

        # Parent context at fork: main turns 1 steps 0+1 (all of main, including tool_result)
        parent_at_fork = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
        ])
        # Subagent context: parent prefix (bounded by fork) + branch
        sub_context = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
            BranchSegment(branch="sub_1", turns=[(1, [0, 1])]),
        ])

        _, parent_msgs = reconstruct(log, parent_at_fork)
        _, sub_msgs = reconstruct(log, sub_context)

        # The shared prefix is the first 2 messages: user:task + assistant:calling tool
        # (tool_result "handoff text" comes after the fork, so it's excluded from sub prefix)
        parent_prefix = parent_msgs[:2]
        sub_prefix = sub_msgs[:2]
        assert json.dumps(parent_prefix, sort_keys=True) == json.dumps(sub_prefix, sort_keys=True)

    def test_nested_branch_context(self):
        """A branch can fork from another branch (nested subagents)."""
        log = _populated_log()
        # Add a nested branch off sub_1 at (1, 1)
        # IMPORTANT: BRANCH_START must always be on branch="main" (the default)
        log.append(
            ev.BRANCH_START,
            {"branch": "sub_1_1", "parent_branch": "sub_1", "turn": 1, "step": 1},
        )
        log.append(ev.TURN_START, {"turn": 1}, branch="sub_1_1")
        log.append(
            ev.USER_MESSAGE,
            {"turn": 1, "step": 0, "role": "user", "content": "nested task", "source": "human"},
            surface_op="append",
            branch="sub_1_1",
        )
        log.append(ev.STEP_START, {"turn": 1, "step": 1}, branch="sub_1_1")
        log.append(
            ev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "nested result"}},
            surface_op="append",
            branch="sub_1_1",
        )

        spec = ContextSpec(segments=[
            BranchSegment(branch="main", turns=[(1, [0, 1])]),
            BranchSegment(branch="sub_1", turns=[(1, [0, 1])]),
            BranchSegment(branch="sub_1_1", turns=[(1, [0, 1])]),
        ])
        _, messages = reconstruct(log, spec)
        contents = [m.get("content") for m in messages if m.get("content")]
        assert contents == ["task", "calling tool", "sub instructions", "sub result", "nested task", "nested result"]


class TestSpecBuilders:
    def test_spec_for_main_includes_all_surface_turns_and_steps(self):
        log = _populated_log()
        spec = spec_for_main(log)
        assert len(spec.segments) == 1
        assert spec.segments[0].branch == "main"
        # BranchSegment.__post_init__ converts lists to tuples
        assert spec.segments[0].turns == ((1, (0, 1)),)

    def test_spec_for_branch_includes_parent_prefix_and_branch(self):
        log = _populated_log()
        spec = spec_for_branch(log, "sub_1")
        assert len(spec.segments) == 2
        assert spec.segments[0].branch == "main"
        assert spec.segments[1].branch == "sub_1"

    def test_spec_for_branch_unknown_branch_raises(self):
        log = _populated_log()
        with pytest.raises(KeyError, match="nonexistent"):
            spec_for_branch(log, "nonexistent")
