"""tests/test_spawn_agent_tool.py — spawn_agent tool and its registration gate."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent._loop_config import AgentCallbacks
from agent.tools import create_tool_registry
from tools.spawn_agent import SpawnAgentTool


def _names(callbacks, tmp_path) -> list[str]:
    with patch("agent.tools._discover_subagent_tools", return_value=[]), \
         patch("agent.tools._load_project_tools", return_value=[]):
        reg = create_tool_registry(cwd=tmp_path, callbacks=callbacks)
    return [name for name, _ in reg.list_tools()]


def test_spawn_agent_absent_without_callback(tmp_path):
    assert "spawn_agent" not in _names(AgentCallbacks(), tmp_path)
    assert "spawn_agent" not in _names(None, tmp_path)


def test_spawn_agent_forwards_stripped_task():
    calls = []

    def fn(slug, task, close_on_done):
        calls.append((slug, task, close_on_done))
        return "Spawned fixer_ab12cd34."

    tool = SpawnAgentTool(spawn=fn)
    result = tool.run("fixer", " do x ", True)

    assert calls == [("fixer", "do x", True)]
    assert result == "Spawned fixer_ab12cd34."


def test_spawn_agent_rejects_bad_types():
    tool = SpawnAgentTool(spawn=lambda slug, task, close_on_done: "")

    with pytest.raises(ValueError):
        tool.run(1, "task")
    with pytest.raises(ValueError):
        tool.run("fixer", "task", "yes")
    with pytest.raises(ValueError):
        tool.run("fixer", "   ")


def test_spawn_agent_registered_last_after_show_file(tmp_path):
    fn = lambda slug, task, close_on_done: ""
    callbacks = AgentCallbacks(board=object(), on_show_file=lambda p, l: None, spawn_agent=fn)

    names = _names(callbacks, tmp_path)

    # spawn_agent is registered right after show_file, within the frontend-tools block.
    assert names.index("spawn_agent") == names.index("show_file") + 1
