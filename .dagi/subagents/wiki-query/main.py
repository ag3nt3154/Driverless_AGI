"""Project wiki query tool; clean child delegation through the public API."""
from agent.base_tool import BaseTool
from tools._wiki_tools import run_wiki


class WikiQueryTool(BaseTool):
    name = "wiki_query"
    description = "Query this project wiki with citations and explicit gaps."
    _parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Question or task to look up."},
            "scope": {"type": "string", "description": "Optional wiki-relative search scope."},
        },
        "required": ["task"],
    }

    def __init__(self, config, callbacks=None, tracker=None, session_log=None,
                 parent_context=None):
        self._config = config
        self._callbacks = callbacks
        self._session_log = session_log
        self._parent_context = parent_context

    def run(self, task: str, scope: str = "") -> str:
        return run_wiki(self, "query", task, scope)
