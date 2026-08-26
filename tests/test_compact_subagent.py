# tests/test_compact_subagent.py
"""Tests for subagent-based compaction in AgentLoop."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import session_events as sev
from agent.loop import AgentConfig, AgentLoop, CompactionResult, _NO_COMPACTION
from agent.session_log import SessionLog


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


def _seed_steps(loop, turn: int, n_steps: int, prefix: str = "task") -> None:
    """Append n_steps of user+assistant surface events to an existing loop."""
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


def _make_loop_with_history(config):
    """Create an AgentLoop with seeded conversation history (5 steps, 2 turns)."""
    loop = AgentLoop(config=config, _registry=_make_registry())
    _seed_steps(loop, turn=1, n_steps=3, prefix="task")
    _seed_steps(loop, turn=2, n_steps=2, prefix="task2")
    loop._last_prompt_tokens = 5_000  # 5 steps Ã— 1000/step avg
    return loop


class TestSubagentCompaction:
    def test_compact_noop_when_no_history(self):
        """No steps â†’ no compaction."""
        loop = AgentLoop(config=_config(), _registry=_make_registry())
        result = loop.compact(force=False)
        assert result.did_compact is False

    def test_compact_noop_when_budget_covers_all(self):
        """When budget covers everything, compact() is a no-op."""
        with patch("agent._compaction.run_subagent") as mock_spawn:
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
        mock_result.handoff_path = Path(".dagi/handoffs/compact_abc12345.md")
        mock_result.branch_id = "compact_abc12345"

        with patch("agent._compaction.run_subagent", return_value=mock_result) as mock_spawn:
            loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
            loop._last_request_snapshot = _SNAPSHOT
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
        mock_result.handoff_path = Path(".dagi/handoffs/compact_fail.md")

        with patch("agent._compaction.run_subagent", return_value=mock_result):
            loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
            loop._last_request_snapshot = _SNAPSHOT
            result = loop.compact(force=True)
            assert result.did_compact is False

    def test_compact_context_swallows_exceptions(self):
        """_compact_context() swallows all exceptions from compact()."""
        with patch("agent._compaction.run_subagent", side_effect=RuntimeError("network down")):
            loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
            loop._last_request_snapshot = _SNAPSHOT
            result = loop._compact_context()
            assert result.did_compact is False

    def test_generation_increments_on_each_compaction(self):
        """Repeated compactions increment the generation counter."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Summary v1."
        mock_result.handoff_path = Path(".dagi/handoffs/compact_a.md")
        mock_result.branch_id = "compact_a"

        with patch("agent._compaction.run_subagent", return_value=mock_result):
            loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
            loop._last_request_snapshot = _SNAPSHOT
            t1 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t1})
            r1 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t1, "reason": {"kind": "completed"}})
            assert r1.generation == 1

        # Add more steps so there's a new middle for the second compaction.
        # After first compaction the surface has 1 surviving tail step + CONTEXT_COMPACTION.
        # Seeding 5 more steps gives 6 visible steps: avg=6000/6=1000 â†’ keep=1 â†’ 5 in middle.
        _seed_steps(loop, turn=3, n_steps=5, prefix="more")
        mock_result.handoff_text = "Summary v2."
        mock_result.handoff_path = Path(".dagi/handoffs/compact_b.md")
        mock_result.branch_id = "compact_b"
        with patch("agent._compaction.run_subagent", return_value=mock_result):
            loop._last_request_snapshot = _SNAPSHOT
            loop._last_prompt_tokens = 6_000  # 6 steps Ã— 1000/step avg
            t2 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t2})
            r2 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t2, "reason": {"kind": "completed"}})
            assert r2.generation == 2


class TestRequestSnapshot:
    def test_snapshot_is_none_before_any_api_call(self):
        """_last_request_snapshot is None on a fresh loop."""
        loop = AgentLoop(config=_config(), _registry=_make_registry())
        assert loop._last_request_snapshot is None

    def test_snapshot_contains_required_fields(self):
        """After an API call, snapshot has model, messages, tools,
        parallel_tool_calls, extra_body, base_url."""
        from unittest.mock import MagicMock, patch
        from types import SimpleNamespace

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(
                    content="done",
                    tool_calls=None,
                ),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )
        with patch.object(loop.client.chat.completions, "create",
                          return_value=fake_response):
            loop.run("hello")

        snap = loop._last_request_snapshot
        assert snap is not None
        assert "model" in snap
        assert "messages" in snap
        assert "tools" in snap
        assert "parallel_tool_calls" in snap
        assert "extra_body" in snap
        assert "base_url" in snap
        assert snap["model"] == "test-model"

    def test_snapshot_messages_are_deep_copied(self):
        """Mutating _messages after capture does not affect the snapshot."""
        from unittest.mock import patch
        from types import SimpleNamespace

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="done", tool_calls=None),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(
                prompt_tokens=10, completion_tokens=5, total_tokens=15,
            ),
        )
        with patch.object(loop.client.chat.completions, "create",
                          return_value=fake_response):
            loop.run("hello")

        snap_msgs_before = [m.copy() for m in loop._last_request_snapshot["messages"]]
        # Mutate _messages â€” snapshot should be unaffected
        loop._messages.clear()
        assert loop._last_request_snapshot["messages"] == snap_msgs_before


class TestCompactOrchestration:
    def test_no_snapshot_returns_no_compaction(self):
        """compact() returns _NO_COMPACTION when _last_request_snapshot is None."""
        loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
        loop._last_request_snapshot = None
        result = loop.compact(force=True)
        assert result.did_compact is False

    def test_compact_creates_retroactive_branch(self):
        """compact() appends BRANCH_START with parent_cut_seq at STEP_END of last summarized step."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.status = "ok"
        mock_result.handoff_text = "Cumulative summary."
        mock_result.handoff_path = Path(".dagi/handoffs/compact_abc.md")

        loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
        loop._last_request_snapshot = _SNAPSHOT

        with patch("agent._compaction.run_subagent", return_value=mock_result):
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        branch_events = [
            e for e in loop.log.events
            if e.type == sev.BRANCH_START and "compact" in e.data.get("branch", "")
        ]
        assert len(branch_events) == 1
        be = branch_events[0]
        assert "parent_cut_seq" in be.data
        cut_seq = be.data["parent_cut_seq"]
        cut_event = next(e for e in loop.log.events if e.seq == cut_seq)
        assert cut_event.type == sev.STEP_END

    def test_stale_generation_rejects_handoff(self):
        """If surface generation changes during compact, handoff is rejected."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Summary."
        mock_result.handoff_path = Path(".dagi/handoffs/compact_stale.md")

        loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
        loop._last_request_snapshot = _SNAPSHOT

        def bump_generation(**kwargs):
            loop.log.surface.generation += 1
            return mock_result

        with patch("agent._compaction.run_subagent", side_effect=bump_generation):
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            result = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        assert result.did_compact is False

    def test_compaction_event_has_provenance(self):
        """CONTEXT_COMPACTION event has branch and handoff fields; the handoff
        path contains the branch id to confirm they reference the same run."""
        import json
        import tempfile

        loop = _make_loop_with_history(_config(keep_recent_tokens=1_500))
        loop._last_request_snapshot = _SNAPSHOT

        # Build a dynamic mock that reads the branch_id from the fork-context
        # file written by compact() and returns a matching handoff path.
        def _dynamic_run_subagent(task, preset, project_path, parent_log, fork_context_path,
                                   **kwargs):
            # fork_context_path is the temp file written by compact()
            fork_ctx = json.loads(Path(fork_context_path).read_text(encoding="utf-8"))
            branch = fork_ctx["branch"]["id"]
            result = MagicMock()
            result.is_ok = True
            result.handoff_text = "Summary."
            result.handoff_path = Path(tempfile.gettempdir()) / f"{branch}.md"
            return result

        with patch("agent._compaction.run_subagent", side_effect=_dynamic_run_subagent):
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        cc = [e for e in loop.log.events if e.type == sev.CONTEXT_COMPACTION]
        assert len(cc) == 1
        assert "branch" in cc[0].data
        assert "compact_" in cc[0].data["branch"]
        assert "handoff" in cc[0].data
        assert cc[0].data["branch"] in cc[0].data.get("handoff", "")
