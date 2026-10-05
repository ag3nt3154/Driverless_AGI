"""tests/test_loop_construction.py — AgentLoop constructor contract (R7 refactor guard).

The constructor wires state that distant methods read much later, so a dropped
or misspelled ``self.x`` would only fail on some rare path. These tests pin the
attribute set, tracker precedence and the default-tier config snapshot.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.loop import AgentConfig, AgentLoop
from tests.test_session_log_shadow import _make_loop

_EXPECTED_ATTRIBUTES = {
    "_abort_request", "_active_stream", "_base_config_snapshot", "_compaction_generation",
    "_continuation_count", "_current_tier", "_effective_memory_root", "_empty_content_streak",
    "_events_path", "_expression_controller", "_expression_timer", "_extra_body", "_in_run",
    "_inject_lock", "_injected", "_injected_bash_tool", "_last_prompt_tokens",
    "_last_request_snapshot", "_lifecycle", "_messages", "_mid_step", "_parallel_tool_calls",
    "_pause_checkpoint", "_pause_event", "_preserve_request_prefix", "_process",
    "_skip_slug_generation", "_system_prefix", "_system_prompt_override", "callbacks",
    "client", "config", "log", "registry", "skills", "system_parts", "tracker", "turns",
}


def _config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(model="m", api_key="k", system_prompt="s", project_path=tmp_path)


def _registry() -> MagicMock:
    reg = MagicMock()
    reg.get_openai_tools_list.return_value = []
    reg.list_tools.return_value = []
    return reg


def _main_loop(tmp_path: Path, **kwargs) -> AgentLoop:
    """Build the main-agent path (skills + create_tool_registry) without real I/O."""
    kwargs.setdefault("tracker", MagicMock())
    with patch("openai.OpenAI"), \
         patch("agent.tools.create_tool_registry", return_value=_registry()), \
         patch("agent.loop.ensure_expression_controller"), \
         patch("agent.loop.SkillLoader"):
        return AgentLoop(config=_config(tmp_path), **kwargs)


def test_subagent_path_attribute_set(tmp_path):
    assert set(vars(_make_loop(tmp_path))) == _EXPECTED_ATTRIBUTES


def test_main_agent_path_attribute_set(tmp_path):
    assert set(vars(_main_loop(tmp_path))) == _EXPECTED_ATTRIBUTES


def test_explicit_tracker_wins_over_parent_tracker(tmp_path):
    explicit, parent = MagicMock(), MagicMock()

    loop = _main_loop(tmp_path, tracker=explicit, _parent_tracker=parent, _subagent_id="abc")

    assert loop.tracker is explicit
    parent.child_tracker.assert_not_called()


def test_parent_tracker_spawns_named_child(tmp_path):
    parent = MagicMock()

    loop = _main_loop(tmp_path, tracker=None, _parent_tracker=parent, _subagent_id="abc")

    parent.child_tracker.assert_called_once_with("abc")
    assert loop.tracker is parent.child_tracker.return_value


def test_without_trackers_a_fresh_one_logs_under_the_project(tmp_path):
    with patch("agent.loop.SessionTracker") as tracker_cls:
        loop = _main_loop(tmp_path, tracker=None)

    tracker_cls.assert_called_once_with(
        model="m", thread_id=None, logs_dir=tmp_path / ".dagi" / "logs",
    )
    assert loop.tracker is tracker_cls.return_value


def test_client_script_request_kwargs_reach_config_and_default_snapshot(tmp_path):
    script_kwargs = {"temperature": 0.2}
    with patch(
        "agent._model_switch.build_openai_client", return_value=(MagicMock(), script_kwargs),
    ):
        loop = _main_loop(tmp_path)

    assert loop.config.request_kwargs == script_kwargs
    assert loop._base_config_snapshot["request_kwargs"] == script_kwargs
    assert loop._base_config_snapshot["request_kwargs"] is not loop.config.request_kwargs
    assert loop._current_tier == "default"
