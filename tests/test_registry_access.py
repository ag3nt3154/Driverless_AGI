"""tests/test_registry_access.py — Dispatch-time tool access denial."""
from __future__ import annotations

from agent.registry import ToolRegistry
from agent.base_tool import BaseTool


class _DummyTool(BaseTool):
    name = "dummy"
    description = "A test tool"
    _parameters = {"type": "object", "properties": {"x": {"type": "string"}}}

    def run(self, x: str = "") -> str:
        return f"result:{x}"


def _registry_with_dummy() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_DummyTool())
    return reg


class TestDeniedTools:
    def test_denied_tool_returns_access_denied_message(self):
        reg = _registry_with_dummy()
        reg.deny({"dummy"})
        result = reg.dispatch("dummy", {"x": "hello"})
        assert "access denied" in result.lower()
        assert "dummy" in result.lower()

    def test_denied_tool_still_appears_in_openai_tools_list(self):
        reg = _registry_with_dummy()
        reg.deny({"dummy"})
        names = [t["function"]["name"] for t in reg.get_openai_tools_list()]
        assert "dummy" in names

    def test_denied_tool_still_appears_in_list_tools(self):
        reg = _registry_with_dummy()
        reg.deny({"dummy"})
        names = [name for name, _ in reg.list_tools()]
        assert "dummy" in names

    def test_non_denied_tool_dispatches_normally(self):
        reg = _registry_with_dummy()
        reg.deny({"other_tool"})
        result = reg.dispatch("dummy", {"x": "hello"})
        assert result == "result:hello"

    def test_deny_with_empty_set_blocks_nothing(self):
        reg = _registry_with_dummy()
        reg.deny(set())
        result = reg.dispatch("dummy", {"x": "hello"})
        assert result == "result:hello"

    def test_clear_denied_restores_access(self):
        reg = _registry_with_dummy()
        reg.deny({"dummy"})
        reg.deny(set())
        result = reg.dispatch("dummy", {"x": "hello"})
        assert result == "result:hello"
