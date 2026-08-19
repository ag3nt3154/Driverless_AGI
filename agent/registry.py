from agent.base_tool import BaseTool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._denied: set[str] = set()

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Return the registered tool named *name*, or ``None``."""
        return self._tools.get(name)

    def get_openai_tools_list(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def list_tools(self) -> list[tuple[str, str]]:
        """Return ``[(name, description), ...]`` for every registered tool."""
        return [(t.name, t.description) for t in self._tools.values()]

    def deny(self, names: set[str]) -> None:
        """Replace the denied-tool set wholesale. Empty set clears all denials."""
        self._denied = set(names)

    def filter_to(self, names: list[str] | None) -> None:
        """Remove any registered tool not in *names*. None keeps all tools."""
        if names is None:
            return
        keep = set(names)
        for name in list(self._tools):
            if name not in keep:
                del self._tools[name]

    def filter_out(self, names: list[str] | None) -> None:
        """Remove tools whose names are in *names*. None is a no-op."""
        if not names:
            return
        for name in names:
            self._tools.pop(name, None)

    def dispatch(self, name: str, kwargs: dict) -> str | list:
        if name not in self._tools:
            return f"Error: unknown tool '{name}'"
        if name in self._denied:
            return f"Access denied: tool '{name}' is not available in this context."
        try:
            return self._tools[name].run(**kwargs)
        except Exception as e:
            return f"Error: {e}"


registry = ToolRegistry()
