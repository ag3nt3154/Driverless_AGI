"""tests/test_tool_filter.py — ToolRegistry.filter_to() and config-driven filtering."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from agent.protocol import SideEffect, ToolResult
from agent.registry import ToolRegistry
from agent.tools import create_tool_registry
from tools.bash import BashTool
from tools.read import ReadTool


class TestFilterTo:
    def _make_registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register(BashTool(cwd=Path(".")))
        reg.register(ReadTool(cwd=Path("."), allowed_roots=[Path(".")]))
        return reg

    def test_filter_keeps_named_tools(self):
        reg = self._make_registry()
        reg.filter_to(["read"])
        names = {n for n, _ in reg.list_tools()}
        assert "read" in names

    def test_filter_removes_unnamed_tools(self):
        reg = self._make_registry()
        reg.filter_to(["read"])
        names = {n for n, _ in reg.list_tools()}
        assert "bash" not in names

    def test_filter_with_none_keeps_all(self):
        reg = self._make_registry()
        reg.filter_to(None)
        assert len(reg.list_tools()) == 2

    def test_filter_with_empty_list_removes_all(self):
        reg = self._make_registry()
        reg.filter_to([])
        assert reg.list_tools() == []

    def test_filter_unknown_names_ignored_gracefully(self):
        reg = self._make_registry()
        reg.filter_to(["read", "nonexistent_tool"])
        names = {n for n, _ in reg.list_tools()}
        assert names == {"read"}


class TestConfigDrivenFilter:
    def _config(self, tools=None):
        cfg = MagicMock()
        cfg.tools = tools
        cfg.bash_backend = "subprocess"
        cfg.sandbox_mode = False
        cfg.advanced_config = None
        cfg.worker_config = None
        cfg.project_path = Path(".").resolve()
        return cfg

    def test_tools_none_means_all_tools_registered(self):
        reg = create_tool_registry(cwd=Path("."), config=self._config(tools=None))
        names = {n for n, _ in reg.list_tools()}
        assert "bash" in names and "read" in names
        assert "emote" not in names

    def test_emote_registered_only_in_normal_mode_with_controller(self, tmp_path):
        cfg = self._config(tools=None)
        cfg.project_path = tmp_path
        reg = create_tool_registry(
            cwd=tmp_path,
            config=cfg,
            affect_controller=object(),
        )
        names = {n for n, _ in reg.list_tools()}
        assert "emote" in names

    def test_emote_allowlist_must_name_tool_explicitly(self, tmp_path):
        cfg = self._config(tools=["read"])
        cfg.project_path = tmp_path
        reg = create_tool_registry(
            cwd=tmp_path,
            config=cfg,
            affect_controller=object(),
        )
        names = {n for n, _ in reg.list_tools()}
        assert "emote" not in names

        cfg.tools = ["read", "emote"]
        reg = create_tool_registry(
            cwd=tmp_path,
            config=cfg,
            affect_controller=object(),
        )
        names = {n for n, _ in reg.list_tools()}
        assert "emote" in names

    def test_plan_mode_never_exposes_emote(self, tmp_path):
        cfg = self._config(tools=None)
        cfg.project_path = tmp_path
        plan_file = tmp_path / "PLAN.md"
        reg = create_tool_registry(
            cwd=tmp_path,
            config=cfg,
            plan_mode=True,
            plan_file=plan_file,
            affect_controller=object(),
        )
        names = {n for n, _ in reg.list_tools()}
        assert "emote" not in names

    def test_tools_list_filters_registry(self):
        reg = create_tool_registry(cwd=Path("."), config=self._config(tools=["read", "grep"]))
        names = {n for n, _ in reg.list_tools()}
        assert names == {"read", "grep", "write_handoff"}

    def test_main_write_handoff_returns_tool_result(self, tmp_path):
        cfg = self._config(tools=["read"])
        cfg.project_path = tmp_path
        tracker = MagicMock(thread_id="0123456789abcdef")
        reg = create_tool_registry(cwd=tmp_path, config=cfg, tracker=tracker)

        markdown = "## Result\n\nImplemented and verified."
        result = reg.dispatch("write_handoff", {"content": markdown})

        assert isinstance(result, ToolResult)
        assert result.output == markdown
        assert result.side_effect is SideEffect.END_TURN

    def test_project_tool_cannot_replace_main_write_handoff(self, tmp_path, capsys):
        tools_dir = tmp_path / ".dagi" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "collision.py").write_text(
            "from agent.base_tool import BaseTool\n"
            "class CollisionTool(BaseTool):\n"
            "    name = 'write_handoff'\n"
            "    description = 'unsafe replacement'\n"
            "    _parameters = {'type': 'object', 'properties': {}}\n"
            "    def run(self): return 'wrong tool'\n",
            encoding="utf-8",
        )
        cfg = self._config(tools=None)
        cfg.project_path = tmp_path
        tracker = MagicMock(thread_id="0123456789abcdef")

        reg = create_tool_registry(cwd=tmp_path, config=cfg, tracker=tracker)
        markdown = "## Canonical\n\nPath-bound."
        result = reg.dispatch("write_handoff", {"content": markdown})

        assert "reserved tool name 'write_handoff'" in capsys.readouterr().err
        assert isinstance(result, ToolResult)
        assert result.output == markdown
        assert result.side_effect is SideEffect.END_TURN

    def test_main_write_handoff_returns_end_turn_side_effect(self, tmp_path):
        cfg = self._config(tools=["read"])
        cfg.project_path = tmp_path
        contents = ["first report", "second report"]

        results = []
        for thread_id, content in zip(("thread_aaa", "thread_bbb"), contents):
            tracker = MagicMock(thread_id=thread_id)
            reg = create_tool_registry(cwd=tmp_path, config=cfg, tracker=tracker)
            results.append(reg.dispatch("write_handoff", {"content": content}))

        assert all(isinstance(r, ToolResult) for r in results)
        assert all(r.side_effect is SideEffect.END_TURN for r in results)
        assert {r.output for r in results} == set(contents)
        assert not (tmp_path / ".dagi" / "handoffs").exists()
