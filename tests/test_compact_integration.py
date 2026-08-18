# tests/test_compact_integration.py
"""Integration tests: subagent-based compaction with session log."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import session_events as sev
from agent.loop import AgentConfig, AgentLoop, CompactionResult, _NO_COMPACTION


_SNAPSHOT = {
    "model": "test-model",
    "messages": [{"role": "system", "content": "You are a test agent."}],
    "tools": [],
    "parallel_tool_calls": False,
    "extra_body": {},
    "base_url": "",
}


def _config(**overrides):
    base = dict(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        keep_recent_tokens=1_500,
        context_window=10_000,
        reserve_tokens=2_000,
    )
    base.update(overrides)
    return AgentConfig(**base)


def _make_registry():
    reg = MagicMock()
    reg.get_openai_tools_list.return_value = []
    reg.list_tools.return_value = []
    return reg


def _seed_steps(loop, turn: int, n_steps: int, prefix: str = "task") -> None:
    """Append n_steps of user+assistant surface events to a loop."""
    log = loop.log
    log.append(sev.TURN_START, {"turn": turn})
    for step in range(n_steps):
        log.append(sev.STEP_START, {"turn": turn, "step": step})
        log.append(
            sev.USER_MESSAGE,
            {"turn": turn, "step": step, "role": "user", "content": f"{prefix} {step}"},
            surface_op="append",
        )
        log.append(
            sev.ASSISTANT_MESSAGE,
            {"turn": turn, "step": step, "message": {"role": "assistant", "content": f"done {step}"}},
            surface_op="append",
        )
        log.append(sev.STEP_END, {"turn": turn, "step": step})
    log.append(sev.TURN_END, {"turn": turn, "reason": {"kind": "completed"}})
    loop._sync_messages()


class TestCompactionSurfaceIntegration:
    def test_compaction_replaces_middle_in_session_log(self):
        """Successful compaction logs CONTEXT_COMPACTION and rebuilds _messages."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Summary of the conversation."
        mock_result.branch_id = "compact_test1"

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000  # 1000/step avg → keep 1, middle 4
        loop._last_request_snapshot = _SNAPSHOT

        with patch("agent.loop.run_subagent", return_value=mock_result):
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            result = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        assert result.did_compact is True
        assert result.generation == 1
        assert result.removed_count == 4  # 4 middle steps

        # Exactly one CONTEXT_COMPACTION event on the surface
        compaction_events = [e for e in loop.log.events if e.type == sev.CONTEXT_COMPACTION]
        assert len(compaction_events) == 1
        assert "Summary of the conversation." in compaction_events[0].data["summary"]

        # _messages has been rebuilt: [header, summary, tail...]
        # Summary is first non-system message, it contains [CONTEXT SUMMARY
        non_system = [m for m in loop._messages if m.get("role") != "system"]
        assert any("[CONTEXT SUMMARY" in str(m.get("content", "")) for m in non_system)

    def test_collect_steps_only_returns_surface_visible_steps(self):
        """After compaction, _collect_steps() must not include already-summarized steps."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Summary v1."
        mock_result.branch_id = "compact_v1"

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT

        # Before compaction: 5 steps visible
        assert len(loop._collect_steps()) == 5

        with patch("agent.loop.run_subagent", return_value=mock_result):
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        # After compaction: only the tail step(s) visible, not the summarized middle
        steps_after = loop._collect_steps()
        # With 5 steps and keep_recent_tokens=1_500, avg=1000 → keep 1
        assert len(steps_after) == 1
        # The surviving step is the last one
        assert steps_after[0] == (1, 4)

    def test_second_compaction_after_new_steps(self):
        """After adding new steps post-compaction, a second compaction works correctly."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Summary."
        mock_result.branch_id = "compact_a"

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT

        with patch("agent.loop.run_subagent", return_value=mock_result):
            t1 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t1})
            r1 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t1, "reason": {"kind": "completed"}})
        assert r1.generation == 1

        # Add more steps so there's a new middle
        _seed_steps(loop, turn=2, n_steps=5)
        loop._last_prompt_tokens = 6_000  # 6 visible steps × 1000/step → keep 1 → 5 middle

        mock_result.handoff_text = "Summary v2."
        mock_result.branch_id = "compact_b"
        with patch("agent.loop.run_subagent", return_value=mock_result):
            loop._last_request_snapshot = _SNAPSHOT
            t2 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t2})
            r2 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t2, "reason": {"kind": "completed"}})
        assert r2.generation == 2

        # Two CONTEXT_COMPACTION events on log
        cc_events = [e for e in loop.log.events if e.type == sev.CONTEXT_COMPACTION]
        assert len(cc_events) == 2

    def test_compact_subagent_failure_leaves_surface_intact(self):
        """When the compact subagent fails, the session log surface is unchanged."""
        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT

        surface_before = list(loop.log.surface.nodes)

        mock_result = MagicMock()
        mock_result.is_ok = False
        mock_result.handoff_text = ""
        with patch("agent.loop.run_subagent", return_value=mock_result):
            result = loop.compact(force=True)

        assert result.did_compact is False
        assert list(loop.log.surface.nodes) == surface_before  # surface unchanged

    def test_messages_list_identity_preserved(self):
        """_messages retains its list identity after compaction (slice assignment)."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Summary."
        mock_result.branch_id = "compact_id"
        mock_result.handoff_path = Path(".dagi/handoffs/compact_id.md")

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT

        original_list = loop._messages

        with patch("agent.loop.run_subagent", return_value=mock_result):
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        assert loop._messages is original_list  # same list object

    def test_raw_events_not_deleted_or_duplicated(self):
        """Original events remain exactly once in the append-only log after compaction."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Summary."
        mock_result.branch_id = "compact_raw"
        mock_result.handoff_path = Path(".dagi/handoffs/compact_raw.md")

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT

        events_before = len(loop.log.events)

        with patch("agent.loop.run_subagent", return_value=mock_result):
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        # More events than before (new BRANCH_START + CONTEXT_COMPACTION added)
        assert len(loop.log.events) > events_before
        # No duplicates — every seq is unique
        seqs = [e.seq for e in loop.log.events]
        assert len(seqs) == len(set(seqs))

    def test_failure_leaves_surface_generation_unchanged(self):
        """Failed compaction must not change surface generation or messages."""
        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT

        gen_before = loop.log.surface.generation
        nodes_before = loop.log.surface.nodes
        msgs_before = [m.copy() for m in loop._messages]

        mock_result = MagicMock()
        mock_result.is_ok = False
        mock_result.handoff_text = ""
        with patch("agent.loop.run_subagent", return_value=mock_result):
            result = loop.compact(force=True)

        assert result.did_compact is False
        assert loop.log.surface.generation == gen_before
        assert loop.log.surface.nodes == nodes_before
        assert [m.get("content") for m in loop._messages] == [
            m.get("content") for m in msgs_before
        ]

    def test_repeated_compaction_summary_replaces_prior(self):
        """A second compaction replaces the prior summary in messages."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Summary v1."
        mock_result.branch_id = "compact_r1"
        mock_result.handoff_path = Path(".dagi/handoffs/compact_r1.md")

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT

        with patch("agent.loop.run_subagent", return_value=mock_result):
            t1 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t1})
            r1 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t1, "reason": {"kind": "completed"}})
        assert r1.generation == 1

        # After compaction, messages contain the summary
        non_sys = [m for m in loop._messages if m.get("role") != "system"]
        assert any("[CONTEXT SUMMARY" in str(m.get("content", "")) for m in non_sys)
        # Shadowed step content not in messages
        for m in non_sys:
            content = str(m.get("content", ""))
            if "[CONTEXT SUMMARY" not in content:
                assert "task 0" not in content

        # Second compaction — add more steps first
        _seed_steps(loop, turn=2, n_steps=5)
        loop._last_prompt_tokens = 6_000
        loop._last_request_snapshot = _SNAPSHOT

        mock_result.handoff_text = "Summary v2."
        mock_result.branch_id = "compact_r2"
        mock_result.handoff_path = Path(".dagi/handoffs/compact_r2.md")

        with patch("agent.loop.run_subagent", return_value=mock_result):
            t2 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t2})
            r2 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t2, "reason": {"kind": "completed"}})
        assert r2.generation == 2

        # Two CONTEXT_COMPACTION events in log (both preserved — append-only)
        cc_events = [e for e in loop.log.events if e.type == sev.CONTEXT_COMPACTION]
        assert len(cc_events) == 2
