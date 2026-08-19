"""Schema-preserving tool registry for inherited subagent execution."""
from __future__ import annotations

from copy import deepcopy

from agent.base_tool import BaseTool
from agent.registry import ToolRegistry


class InheritedSchemaTool(BaseTool):
    """Expose a provider schema while forwarding calls to an allowed tool."""

    def __init__(
        self,
        schema: dict,
        allowed_registry: ToolRegistry,
        allowed_names: set[str],
        subagent_type: str,
    ) -> None:
        self._schema = deepcopy(schema)
        self.name = self._schema["function"]["name"]
        self.description = self._schema["function"].get("description", "")
        self._parameters = self._schema["function"].get("parameters", {})
        self._allowed_registry = allowed_registry
        self._allowed_names = allowed_names
        self._subagent_type = subagent_type

    def schema(self) -> dict:
        return deepcopy(self._schema)

    def run(self, **kwargs) -> str | list:
        tool = self._allowed_registry.get(self.name)
        if self.name not in self._allowed_names or tool is None:
            allowed = ", ".join(sorted(self._allowed_names)) or "none"
            return (
                f"Error: Access blocked for tool '{self.name}' in subagent "
                f"'{self._subagent_type}'. Allowed tools: {allowed}"
            )
        return tool.run(**kwargs)


def build_inherited_registry(
    schemas: list[dict],
    allowed_registry: ToolRegistry,
    allowed_names: set[str],
    subagent_type: str,
) -> ToolRegistry:
    """Build a registry with exactly the supplied provider-visible schemas."""
    registry = ToolRegistry()
    for schema in schemas:
        registry.register(
            InheritedSchemaTool(schema, allowed_registry, allowed_names, subagent_type)
        )
    return registry
