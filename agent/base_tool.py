from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.protocol import ToolResult


class BaseTool(ABC):
    name: str
    description: str
    _parameters: dict

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._parameters,
            },
        }

    @abstractmethod
    def run(self, **kwargs) -> "str | list | ToolResult": ...
