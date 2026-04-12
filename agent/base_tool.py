from abc import ABC, abstractmethod


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
    def run(self, **kwargs) -> str | list: ...
