"""tests/test_registry.py — Unit tests for ToolRegistry."""
from __future__ import annotations

import pytest

from agent.base_tool import BaseTool
from agent.registry import ToolRegistry


class FakeTool(BaseTool):
    """Minimal BaseTool double for registry tests."""

    def __init__(self, name="fake", description="A fake tool", run_result="ok", run_error=None):
        self.name = name
        self.description = description
        self._parameters = {"type": "object", "properties": {}, "required": []}
        self._run_result = run_result
        self._run_error = run_error
        self.calls: list[dict] = []

    def run(self, **kwargs) -> str | list:
        self.calls.append(kwargs)
        if self._run_error is not None:
            raise self._run_error
        return self._run_result


class TestRegister:
    def test_register_adds_tool(self):
        reg = ToolRegistry()
        tool = FakeTool(name="alpha")
        reg.register(tool)
        assert reg.list_tools() == [("alpha", "A fake tool")]

    def test_register_duplicate_name_raises(self):
        reg = ToolRegistry()
        reg.register(FakeTool(name="alpha"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(FakeTool(name="alpha"))


class TestGetOpenAIToolsList:
    def test_returns_schema_for_each_tool(self):
        reg = ToolRegistry()
        reg.register(FakeTool(name="alpha", description="Does alpha things"))
        reg.register(FakeTool(name="beta", description="Does beta things"))

        schemas = reg.get_openai_tools_list()

        names = {s["function"]["name"] for s in schemas}
        assert names == {"alpha", "beta"}
        assert all(s["type"] == "function" for s in schemas)

    def test_empty_registry_returns_empty_list(self):
        reg = ToolRegistry()
        assert reg.get_openai_tools_list() == []


class TestListTools:
    def test_lists_name_description_pairs(self):
        reg = ToolRegistry()
        reg.register(FakeTool(name="alpha", description="Alpha desc"))
        assert reg.list_tools() == [("alpha", "Alpha desc")]


class TestFilterTo:
    def test_none_keeps_all_tools(self):
        reg = ToolRegistry()
        reg.register(FakeTool(name="alpha"))
        reg.register(FakeTool(name="beta"))
        reg.filter_to(None)
        assert {n for n, _ in reg.list_tools()} == {"alpha", "beta"}

    def test_filters_to_named_subset(self):
        reg = ToolRegistry()
        reg.register(FakeTool(name="alpha"))
        reg.register(FakeTool(name="beta"))
        reg.register(FakeTool(name="gamma"))

        reg.filter_to(["alpha", "gamma"])

        assert {n for n, _ in reg.list_tools()} == {"alpha", "gamma"}

    def test_filter_to_unknown_name_is_ignored(self):
        reg = ToolRegistry()
        reg.register(FakeTool(name="alpha"))
        reg.filter_to(["alpha", "does-not-exist"])
        assert {n for n, _ in reg.list_tools()} == {"alpha"}

    def test_filter_to_empty_list_removes_all(self):
        reg = ToolRegistry()
        reg.register(FakeTool(name="alpha"))
        reg.filter_to([])
        assert reg.list_tools() == []


class TestDispatch:
    def test_dispatch_unknown_tool_returns_error_string(self):
        reg = ToolRegistry()
        result = reg.dispatch("nonexistent", {})
        assert result == "Error: unknown tool 'nonexistent'"

    def test_dispatch_calls_tool_run_with_kwargs(self):
        reg = ToolRegistry()
        tool = FakeTool(name="alpha", run_result="ran ok")
        reg.register(tool)

        result = reg.dispatch("alpha", {"x": 1, "y": "two"})

        assert result == "ran ok"
        assert tool.calls == [{"x": 1, "y": "two"}]

    def test_dispatch_catches_exception_and_returns_error_string(self):
        reg = ToolRegistry()
        tool = FakeTool(name="alpha", run_error=RuntimeError("boom"))
        reg.register(tool)

        result = reg.dispatch("alpha", {})

        assert result == "Error: boom"

    def test_dispatch_can_return_a_list(self):
        reg = ToolRegistry()
        tool = FakeTool(name="alpha", run_result=[{"type": "text", "text": "hi"}])
        reg.register(tool)

        result = reg.dispatch("alpha", {})

        assert result == [{"type": "text", "text": "hi"}]
