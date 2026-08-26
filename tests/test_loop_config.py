"""Verify the loop dataclasses are importable from their dedicated module.

Why this matters: AgentConfig/AgentCallbacks/CompactionResult are imported by
every entry point (TUI, PySide, subagents, benchmarks). The extraction to
agent/_loop_config.py must preserve both the definitions and the re-export
surface of agent.loop.
"""
from agent._loop_config import (
    _NO_COMPACTION,
    AgentCallbacks,
    AgentConfig,
    CompactionResult,
)


def test_agent_config_defaults():
    cfg = AgentConfig()
    assert cfg.model == "gpt-4o"
    assert cfg.context_window == 128_000
    assert cfg.stream is False
    assert cfg.max_continuations == 10
    assert cfg.worker_config is None


def test_agent_callbacks_defaults():
    cb = AgentCallbacks()
    assert cb.supports_pause is False
    assert cb.on_subagent_event_factory is None


def test_compaction_result():
    r = CompactionResult(
        did_compact=True, generation=1, summary_content="s", removed_count=5
    )
    assert r.did_compact is True
    assert r.generation == 1
    assert _NO_COMPACTION.did_compact is False


def test_reexport_from_agent_loop():
    # Backward-compat contract: existing importers keep working unchanged.
    from agent import loop as loop_mod

    assert loop_mod.AgentConfig is AgentConfig
    assert loop_mod.AgentCallbacks is AgentCallbacks
    assert loop_mod.CompactionResult is CompactionResult
