from __future__ import annotations

from agent.base_tool import BaseTool
from agent.inherited_registry import build_inherited_registry
from agent.registry import ToolRegistry


class FakeTool(BaseTool):
    def __init__(self, name: str, result: str = "ok") -> None:
        self.name = name
        self.description = f"{name} description"
        self._parameters = {"type": "object", "properties": {"x": {"type": "string"}}}
        self.result = result
        self.calls: list[dict] = []

    def run(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.result


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"provider schema for {name}",
            "parameters": {"type": "object", "properties": {"arg": {"type": "integer"}}},
        },
    }


def test_inherited_registry_preserves_exact_schema_content_and_order() -> None:
    schemas = [_schema("second"), _schema("first")]
    allowed = ToolRegistry()

    inherited = build_inherited_registry(schemas, allowed, set(), "worker")

    assert inherited.get_openai_tools_list() == schemas
    schemas[0]["function"]["description"] = "mutated"
    assert inherited.get_openai_tools_list()[0]["function"]["description"] == (
        "provider schema for second"
    )


def test_allowed_tool_delegates_to_real_tool() -> None:
    allowed = ToolRegistry()
    tool = FakeTool("read", result="read result")
    allowed.register(tool)
    inherited = build_inherited_registry([_schema("read")], allowed, {"read"}, "worker")

    assert inherited.dispatch("read", {"path": "file.txt"}) == "read result"
    assert tool.calls == [{"path": "file.txt"}]


def test_disallowed_tool_returns_exact_blocked_error() -> None:
    inherited = build_inherited_registry(
        [_schema("write")], ToolRegistry(), {"zeta", "alpha"}, "worker"
    )

    assert inherited.dispatch("write", {}) == (
        "Error: Access blocked for tool 'write' in subagent 'worker'. "
        "Allowed tools: alpha, zeta"
    )


def test_allowed_but_missing_tool_returns_blocked_error() -> None:
    inherited = build_inherited_registry([_schema("read")], ToolRegistry(), {"read"}, "worker")

    assert inherited.dispatch("read", {}) == (
        "Error: Access blocked for tool 'read' in subagent 'worker'. "
        "Allowed tools: read"
    )


def test_empty_allowed_names_use_none_in_blocked_error() -> None:
    inherited = build_inherited_registry([_schema("read")], ToolRegistry(), set(), "worker")

    assert inherited.dispatch("read", {}) == (
        "Error: Access blocked for tool 'read' in subagent 'worker'. Allowed tools: none"
    )


def test_registry_get_returns_tool_or_none_without_changing_dispatch() -> None:
    registry = ToolRegistry()
    tool = FakeTool("read")
    registry.register(tool)

    assert registry.get("read") is tool
    assert registry.get("missing") is None
    assert registry.dispatch("read", {}) == "ok"
