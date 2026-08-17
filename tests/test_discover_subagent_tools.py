"""Tests for the import-based _discover_subagent_tools()."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agent.base_tool import BaseTool
from agent.subagent_tools import _discover_subagent_tools


def _make_args(project_path: Path):
    config = MagicMock()
    config.project_path = project_path
    callbacks = MagicMock()
    callbacks.on_subagent_event_factory = None
    tracker = MagicMock()
    tracker._depth = 0
    return config, callbacks, tracker


def test_discovers_tool_from_main_py(tmp_path, monkeypatch):
    import agent.subagent_tools
    monkeypatch.setattr(agent.subagent_tools, "_DAGI_ROOT", tmp_path)

    sub_dir = tmp_path / ".dagi" / "subagents" / "test_type"
    sub_dir.mkdir(parents=True)
    (sub_dir / "main.py").write_text(
        "from agent.base_tool import BaseTool\n\n"
        "class TestTool(BaseTool):\n"
        "    name = 'test_type_tool'\n"
        "    description = 'Test'\n"
        "    _parameters = {'type': 'object', 'properties': {}}\n"
        "    def __init__(self, config=None, callbacks=None, tracker=None, session_log=None):\n"
        "        self._session_log = session_log\n"
        "    def run(self, **kw): return 'ok'\n",
        encoding="utf-8",
    )

    config, cb, tr = _make_args(tmp_path)
    tools = _discover_subagent_tools(
        cwd=tmp_path, config=config, callbacks=cb, tracker=tr,
    )

    assert len(tools) == 1
    assert tools[0].name == "test_type_tool"


def test_skips_directory_without_main_py(tmp_path, monkeypatch):
    import agent.subagent_tools
    monkeypatch.setattr(agent.subagent_tools, "_DAGI_ROOT", tmp_path)

    sub_dir = tmp_path / ".dagi" / "subagents" / "no_main"
    sub_dir.mkdir(parents=True)
    # No main.py

    config, cb, tr = _make_args(tmp_path)
    tools = _discover_subagent_tools(
        cwd=tmp_path, config=config, callbacks=cb, tracker=tr,
    )

    assert len(tools) == 0


def test_project_overrides_dagi_root(tmp_path, monkeypatch):
    import agent.subagent_tools
    monkeypatch.setattr(agent.subagent_tools, "_DAGI_ROOT", tmp_path / "dagi_root")

    # DAGI root has a type
    dagi_dir = tmp_path / "dagi_root" / ".dagi" / "subagents" / "shared_type"
    dagi_dir.mkdir(parents=True)
    (dagi_dir / "main.py").write_text(
        "from agent.base_tool import BaseTool\n\n"
        "class RootTool(BaseTool):\n"
        "    name = 'shared_type_tool'\n"
        "    description = 'Root version'\n"
        "    _parameters = {'type': 'object', 'properties': {}}\n"
        "    def __init__(self, **kw): pass\n"
        "    def run(self, **kw): return 'root'\n",
        encoding="utf-8",
    )

    # Project has same type — should override
    proj_dir = tmp_path / "project" / ".dagi" / "subagents" / "shared_type"
    proj_dir.mkdir(parents=True)
    (proj_dir / "main.py").write_text(
        "from agent.base_tool import BaseTool\n\n"
        "class ProjectTool(BaseTool):\n"
        "    name = 'shared_type_tool'\n"
        "    description = 'Project version'\n"
        "    _parameters = {'type': 'object', 'properties': {}}\n"
        "    def __init__(self, **kw): pass\n"
        "    def run(self, **kw): return 'project'\n",
        encoding="utf-8",
    )

    config, cb, tr = _make_args(tmp_path / "project")
    tools = _discover_subagent_tools(
        cwd=tmp_path / "project", config=config, callbacks=cb, tracker=tr,
    )

    assert len(tools) == 1
    assert tools[0].description == "Project version"
