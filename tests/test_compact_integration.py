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
        mock_result.handoff_path = Path(".dagi/handoffs/compact_test1.md")

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000  # 1000/step avg â†’ keep 1, middle 4
        loop._last_request_snapshot = _SNAPSHOT

        with patch("agent._compaction.run_subagent", return_value=mock_result):
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            result = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        assert result.did_compact is True
        assert result.generation == 1
        assert result.removed_count == 3  # steps 1-3 (step 0 excluded from compaction)

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
        mock_result.handoff_path = Path(".dagi/handoffs/compact_v1.md")

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT

        # Before compaction: 5 steps visible
        assert len(loop._collect_steps()) == 5

        with patch("agent._compaction.run_subagent", return_value=mock_result):
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        # After compaction: only the tail step(s) visible, not the summarized middle
        steps_after = loop._collect_steps()
        # With 5 steps and keep_recent_tokens=1_500, avg=1000 â†’ keep 1
        assert len(steps_after) == 1
        # The surviving step is the last one
        assert steps_after[0] == (1, 4)

    def test_second_compaction_after_new_steps(self):
        """After adding new steps post-compaction, a second compaction works correctly."""
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.handoff_text = "Summary."
        mock_result.branch_id = "compact_a"
        mock_result.handoff_path = Path(".dagi/handoffs/compact_a.md")

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT

        with patch("agent._compaction.run_subagent", return_value=mock_result):
            t1 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t1})
            r1 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t1, "reason": {"kind": "completed"}})
        assert r1.generation == 1

        # Add more steps so there's a new middle
        _seed_steps(loop, turn=2, n_steps=5)
        loop._last_prompt_tokens = 6_000  # 6 visible steps Ã— 1000/step â†’ keep 1 â†’ 5 middle

        mock_result.handoff_text = "Summary v2."
        mock_result.branch_id = "compact_b"
        with patch("agent._compaction.run_subagent", return_value=mock_result):
            loop._last_request_snapshot = _SNAPSHOT
            t2 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t2})
            r2 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t2, "reason": {"kind": "completed"}})
        assert r2.generation == 2

        # Two CONTEXT_COMPACTION events on log
        cc_events = [e for e in loop.log.events if e.type == sev.CONTEXT_COMPACTION]
        assert len(cc_events) == 2

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

        with patch("agent._compaction.run_subagent", return_value=mock_result):
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

        with patch("agent._compaction.run_subagent", return_value=mock_result):
            t = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t})
            loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t, "reason": {"kind": "completed"}})

        # More events than before (new BRANCH_START + CONTEXT_COMPACTION added)
        assert len(loop.log.events) > events_before
        # No duplicates â€” every seq is unique
        seqs = [e.seq for e in loop.log.events]
        assert len(seqs) == len(set(seqs))

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

        with patch("agent._compaction.run_subagent", return_value=mock_result):
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

        # Second compaction â€” add more steps first
        _seed_steps(loop, turn=2, n_steps=5)
        loop._last_prompt_tokens = 6_000
        loop._last_request_snapshot = _SNAPSHOT

        mock_result.handoff_text = "Summary v2."
        mock_result.branch_id = "compact_r2"
        mock_result.handoff_path = Path(".dagi/handoffs/compact_r2.md")

        with patch("agent._compaction.run_subagent", return_value=mock_result):
            t2 = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": t2})
            r2 = loop.compact(force=True)
            loop.log.append(sev.TURN_END, {"turn": t2, "reason": {"kind": "completed"}})
        assert r2.generation == 2

        # Two CONTEXT_COMPACTION events in log (both preserved â€” append-only)
        cc_events = [e for e in loop.log.events if e.type == sev.CONTEXT_COMPACTION]
        assert len(cc_events) == 2

        # _messages now reflects v2 summary, not v1 â€” the replacement actually happened
        non_sys2 = [m for m in loop._messages if m.get("role") != "system"]
        all_content = " ".join(str(m.get("content", "")) for m in non_sys2)
        assert "Summary v2." in all_content, "Second summary should be present in messages"
        assert "Summary v1." not in all_content, "First summary should be gone from messages"

    def test_default_model_compaction_reduces_next_request(self, tmp_path):
        """Compaction uses the project default even when the parent selected a different provider."""
        from types import SimpleNamespace

        from tools.compact._tail_boundary import estimate_tokens
        from tools.subagent_api import SubagentResult
        from tools.subagent_main import run_forked_compact_mode

        config_dir = tmp_path / ".dagi"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "default_model: compact-regression-provider\n"
            "models:\n"
            "  compact-regression-provider:\n"
            "    model: compact-regression-api-name\n"
            "    api_url: https://compact.example/v1\n"
            "    api_key: test-key\n"
            "    thinking: low\n"
            "    provider_order: [default-provider]\n",
            encoding="utf-8",
        )
        loop = AgentLoop(
            config=_config(project_path=tmp_path), _registry=_make_registry()
        )
        _seed_steps(loop, turn=1, n_steps=5, prefix="history " * 500)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = {
            **_SNAPSHOT,
            "model": "parent-explicit-model",
            "base_url": "https://parent.example/v1",
            "extra_body": {"provider": {"order": ["parent-provider"]}},
        }
        before = sum(map(estimate_tokens, loop._build_request_messages()[1:]))
        provider = MagicMock()
        provider.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="Retained task summary.", tool_calls=None),
                finish_reason="stop",
            )],
            usage=None,
        )

        def run_compact_worker(**kwargs):
            handoff = tmp_path / "compact.md"
            run_forked_compact_mode(
                kwargs["fork_context_path"], str(handoff), "compact", str(tmp_path)
            )
            return SubagentResult("ok", handoff.read_text(encoding="utf-8"), handoff, None, None)

        with patch("agent._compaction.run_subagent", side_effect=run_compact_worker), \
                patch("openai.OpenAI", return_value=provider) as client:
            turn = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": turn})
            result = loop.compact()
            loop.log.append(sev.TURN_END, {"turn": turn, "reason": {"kind": "completed"}})

        client.assert_called_once_with(api_key="test-key", base_url="https://compact.example/v1")
        assert provider.chat.completions.create.call_args.kwargs["model"] == (
            "compact-regression-api-name"
        )
        options = provider.chat.completions.create.call_args.kwargs
        assert options["extra_body"]["provider"]["order"] == ["default-provider"]
        assert options["extra_body"]["reasoning"] == {"effort": "low"}
        request = loop._build_request_messages()
        assert result.did_compact
        assert "Retained task summary." in request[1]["content"]
        assert sum(map(estimate_tokens, request[1:])) < before / 2

    @pytest.mark.parametrize("mode", ["error", "empty", "timeout", "exception", "prepare"])
    @pytest.mark.parametrize("summarize_all", [False, True])
    def test_failure_removes_only_selected_chunk_and_preserves_raw_log(self, mode, summarize_all):
        """Failure must shrink active context without losing the tail or durable history."""
        from agent.session_log import SessionLog
        from tools.compact._tail_boundary import estimate_tokens
        from tools.subagent_api import SubagentResult

        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5, prefix="history " * 500)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT
        before = loop._build_request_messages()
        raw_before = loop.log.events
        nodes_before = loop.log.surface.nodes
        tail_index = len(nodes_before) if summarize_all else (
            loop._find_surface_index_for_step((1, 4))
        )
        tail_nodes = nodes_before[tail_index:]
        loop.callbacks.on_assistant_text = MagicMock()
        loop.callbacks.on_compaction = MagicMock()
        failure = SubagentResult(
            "ok" if mode == "empty" else mode, "", Path("compact.md"), None, None,
            message="worker failed" if mode == "error" else "",
            output_log_path=Path("compact.output.log"),
        )
        effect = RuntimeError("network down") if mode == "exception" else None
        target = "agent.image_assets.materialize_messages" if mode == "prepare" else (
            "agent._compaction.run_subagent"
        )
        if mode == "prepare":
            effect = RuntimeError("image missing")
        with patch(target, return_value=failure, side_effect=effect):
            turn = loop.log.next_turn()
            loop.log.append(sev.TURN_START, {"turn": turn})
            result = loop.compact(summarize_all=summarize_all)
            loop.log.append(sev.TURN_END, {"turn": turn, "reason": {"kind": "completed"}})

        request = loop._build_request_messages()
        assert result.did_compact
        assert "without a summary" in request[1]["content"]
        assert request[2:] == before[tail_index + 1:]
        assert loop.log.surface.nodes[1:] == tail_nodes
        assert sum(map(estimate_tokens, request)) < sum(map(estimate_tokens, before))
        assert loop.log.events[:len(raw_before)] == raw_before
        event = next(e for e in loop.log.events if e.type == sev.CONTEXT_COMPACTION)
        assert event.source_seqs == nodes_before[:tail_index]
        assert event.data["fallback"] is True
        assert SessionLog(loop.log.events).derive_messages() == loop.log.derive_messages()
        loop.callbacks.on_compaction.assert_called_once_with(
            0 if summarize_all else 1, 4 if summarize_all else 3,
        )
        warning = loop.callbacks.on_assistant_text.call_args.args[0]
        assert "context compaction failed" in warning
        assert "removed" in warning

    def test_failed_worker_does_not_remove_changed_surface(self):
        """Failure fallback must never apply its stale selection after another replacement."""
        loop = AgentLoop(config=_config(), _registry=_make_registry())
        _seed_steps(loop, turn=1, n_steps=5)
        loop._last_prompt_tokens = 5_000
        loop._last_request_snapshot = _SNAPSHOT
        before = loop._build_request_messages()

        def stale_failure(**kwargs):
            loop.log.surface.generation += 1
            raise RuntimeError("worker failed after context changed")

        with patch("agent._compaction.run_subagent", side_effect=stale_failure):
            result = loop.compact()
        assert not result.did_compact
        assert loop._build_request_messages() == before
