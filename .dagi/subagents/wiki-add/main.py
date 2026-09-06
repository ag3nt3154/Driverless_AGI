"""Project wiki add tool; clean child delegation through the public API."""
from agent.base_tool import BaseTool
from tools._wiki_tools import run_wiki


class WikiAddTool(BaseTool):
    name = "wiki_add"
    description = "Store main-selected points in this project wiki, preserving conflicts."
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "Explicit selected points and supplied evidence, dates, "
                    "approval/completion context."
                ),
            },
        },
        "required": ["task"],
    }

    def __init__(self, config, callbacks=None, tracker=None, session_log=None,
                 parent_context=None):
        self._config = config
        self._callbacks = callbacks
        self._session_log = session_log
        self._parent_context = parent_context

    def run(self, task: str) -> str:
        return run_wiki(self, "add", task)
