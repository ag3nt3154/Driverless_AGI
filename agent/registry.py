from agent.base_tool import BaseTool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get_openai_tools_list(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def dispatch(self, name: str, kwargs: dict) -> str | list:
        if name not in self._tools:
            return f"Error: unknown tool '{name}'"
        try:
            return self._tools[name].run(**kwargs)
        except Exception as e:
            return f"Error: {e}"


registry = ToolRegistry()
