"""tests/test_tool_filter.py — ToolRegistry.filter_to() and config-driven filtering."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock
import pytest
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

    def test_tools_list_filters_registry(self):
        reg = create_tool_registry(cwd=Path("."), config=self._config(tools=["read", "grep"]))
        names = {n for n, _ in reg.list_tools()}
        assert names == {"read", "grep"}
