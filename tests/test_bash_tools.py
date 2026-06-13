"""tests/test_bash_tools.py — coexistence of bash and injected bash tools."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from agent.tools import create_tool_registry
from tools.bash import BashTool


class _FakeBashTool:
    name = "tmux_bash"
    description = "Fake tmux bash"
    def schema(self): return {}
    def run(self, command: str) -> str: return ""


class TestBashCoexistence:
    def test_bash_always_registered(self):
        """BashTool must be registered even when a _bash_tool is injected."""
        reg = create_tool_registry(cwd=Path("."), bash_tool=_FakeBashTool())
        names = {n for n, _ in reg.list_tools()}
        assert "bash" in names

    def test_injected_tool_also_registered(self):
        """Injected bash tool must be registered alongside bash, not replacing it."""
        reg = create_tool_registry(cwd=Path("."), bash_tool=_FakeBashTool())
        names = {n for n, _ in reg.list_tools()}
        assert "tmux_bash" in names

    def test_no_injection_still_registers_bash(self):
        reg = create_tool_registry(cwd=Path("."))
        names = {n for n, _ in reg.list_tools()}
        assert "bash" in names

    def test_harbor_bash_name_is_harbor_bash(self):
        """HarborBashTool.name must be 'harbor_bash', not 'bash'."""
        from benchmarks.harbor.bash_tool import HarborBashTool
        tool = HarborBashTool(exec_fn=lambda c, t: "")
        assert tool.name == "harbor_bash"

    def test_tmux_bash_importable_from_tools(self):
        """tools.tmux_bash.TmuxBashTool must be importable and have name 'tmux_bash'."""
        from tools.tmux_bash import TmuxBashTool
        assert TmuxBashTool.name == "tmux_bash"
