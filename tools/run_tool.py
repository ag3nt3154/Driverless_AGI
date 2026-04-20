from __future__ import annotations

import json

from agent.base_tool import BaseTool
from agent.registry import ToolRegistry


class RunToolTool(BaseTool):
    name = "run_tool"
    description = (
        "Execute a hidden tool or skill by name. "
        "Call tool_search first to discover the correct name and args format. "
        "Pass args as a JSON string matching the tool's parameter schema."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Exact tool or skill name returned by tool_search.",
            },
            "args": {
                "type": "string",
                "description": (
                    "JSON string of arguments for the tool. "
                    'Example: \'{"task": "find all uses of BaseTool"}\'. '
                    "Use '{}' for tools with no required parameters."
                ),
            },
        },
        "required": ["name", "args"],
    }

    def __init__(self, hidden_registry: ToolRegistry) -> None:
        self._hidden_registry = hidden_registry

    def run(self, name: str, args: str) -> str:
        try:
            kwargs = json.loads(args)
        except json.JSONDecodeError as e:
            return (
                f"Error: args is not valid JSON — {e}. "
                'Pass a JSON string, e.g. \'{"task": "..."}\''
            )

        if not isinstance(kwargs, dict):
            return "Error: args must be a JSON object (dict), not a list or scalar."

        if name not in self._hidden_registry._tools:
            available = ", ".join(sorted(self._hidden_registry._tools.keys()))
            return (
                f"Error: unknown tool '{name}'. "
                f"Known hidden tools: {available}. "
                "Call tool_search to discover the correct name."
            )

        return self._hidden_registry.dispatch(name, kwargs)
