# tests/test_compact_subagent.py
"""Tests for subagent-based compaction in AgentLoop."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent import session_events as sev
from agent.loop import AgentConfig, AgentLoop, CompactionResult, _NO_COMPACTION
from agent.session_log import SessionLog


def _config(**overrides):
    base = dict(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        keep_recent_tokens=2_000,
        context_window=10_000,
        reserve_tokens=2_000,
    )
    base.update(overrides)
    return AgentConfig(**base)


def _make_registry() -> MagicMock:
    """Minimal registry mock that satisfies AgentLoop.__init__."""
    reg = MagicMock()
    reg.get_openai_tools_list.return_value = []
    reg.list_tools.return_value = []
    return reg


def _make_loop_with_history(config):
    """Create an AgentLoop with seeded conversation history."""
    loop = AgentLoop(config=config, _registry=_make_registry())
    log = loop.log

    # Seed 5 steps across 2 turns
    log.append(sev.TURN_START, {"turn": 1})
    for step in range(3):
        log.append(sev.STEP_START, {"turn": 1, "step": step})
        log.append(
            sev.USER_MESSAGE,
            {"turn": 1, "step": step, "role": "user", "content": f"task {step}"},
            surface_op="append",
        )
        log.append(
            sev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": step, "message": {"role": "assistant", "content": f"done {step}"}},
            surface_op="append",
        )
        log.append(sev.STEP_END, {"turn": 1, "step": step})
    log.append(sev.TURN_END, {"turn": 1, "reason": {"kind": "completed"}})

    log.append(sev.TURN_START, {"turn": 2})
    for step in range(2):
        log.append(sev.STEP_START, {"turn": 2, "step": step})
        log.append(
            sev.USER_MESSAGE,
            {"turn": 2, "step": step, "role": "user", "content": f"task2 {step}"},
            surface_op="append",
        )
        log.append(
            sev.ASSISTANT_MESSAGE,
            {"turn": 2, "step": step, "message": {"role": "assistant", "content": f"done2 {step}"}},
            surface_op="append",
        )
        log.append(sev.STEP_END, {"turn": 2, "step": step})
    log.append(sev.TURN_END, {"turn": 2, "reason": {"kind": "completed"}})

    loop._sync_messages()
    loop._last_prompt_tokens = 5_000  # 5 steps × 1000/step avg
    return loop


class TestSubagentCompaction:
    def test_compact_noop_when_no_history(self):
        """No steps → no compaction."""
        loop = AgentLoop(config=_config(), _registry=_make_registry())
        result = loop.compact(force=False)
        assert result.did_compact is False

    def test_compact_noop_when_budget_covers_all(self):
        """When budget covers everything, compact() is a no-op."""
        with patch("agent.loop.run_subagent") as mock_spawn:
            loop = _make_loop_with_history(_config(keep_recent_tokens=100_000))
            result = loop.compact(force=False)
            mock_spawn.assert_not_called()
            assert result.did_compact is False

    def test_compact_spawns_subagent_and_logs_compaction(self):
        """compact() must call run_subagent with preset='compact' and
        log a CONTEXT_COMPACTION event on success."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Cumulative summary of the conversation."
        mock_result.branch_id = "compact_abc12345"

        with patch("agent.loop.run_subagent", return_value=mock_result) as mock_spawn:
            loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
            # compact() appends a surface event which requires an open turn
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            result = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

            # run_subagent was called with preset="compact"
            mock_spawn.assert_called_once()
            kwargs = mock_spawn.call_args.kwargs
            assert kwargs.get("preset") == "compact"

        # CONTEXT_COMPACTION event was logged
        compaction_events = [
            e for e in loop.log.events
            if e.type == sev.CONTEXT_COMPACTION
        ]
        assert len(compaction_events) == 1
        assert "Cumulative summary" in compaction_events[0].data["summary"]
        assert result.did_compact is True
        assert result.generation == 1

    def test_compact_failure_returns_no_compaction(self):
        """When subagent returns is_ok=False, compact() returns _NO_COMPACTION."""
        mock_result = MagicMock()
        mock_result.is_ok = False
        mock_result.handoff_text = ""

        with patch("agent.loop.run_subagent", return_value=mock_result):
            loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
            result = loop.compact(force=True)
            assert result.did_compact is False

    def test_compact_context_swallows_exceptions(self):
        """_compact_context() swallows all exceptions from compact()."""
        with patch("agent.loop.run_subagent", side_effect=RuntimeError("network down")):
            loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
            result = loop._compact_context()
            assert result.did_compact is False

    def test_generation_increments_on_each_compaction(self):
        """Repeated compactions increment the generation counter."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Summary v1."
        mock_result.branch_id = "compact_a"

        with patch("agent.loop.run_subagent", return_value=mock_result):
            loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
            t1 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t1})
            r1 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t1, "reason": {"kind": "completed"}})
            assert r1.generation == 1

        # Second compaction — the tail from the first compaction becomes the new history
        mock_result.handoff_text = "Summary v2."
        mock_result.branch_id = "compact_b"
        with patch("agent.loop.run_subagent", return_value=mock_result):
            loop._last_prompt_tokens = 5_000
            t2 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t2})
            r2 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t2, "reason": {"kind": "completed"}})
            assert r2.generation == 2
