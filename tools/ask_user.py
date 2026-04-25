from __future__ import annotations

import json
from typing import Callable

from agent.base_tool import BaseTool


class AskUserTool(BaseTool):
    name = "ask_user"
    description = (
        "Pause planning and present the user with a question. "
        "Use during user-initiated plan mode to resolve ambiguities, choose between approaches, "
        "confirm architectural decisions, or collect free-text feedback. "
        "Optionally provide 2-4 concrete options; omit options entirely to ask a free-text question. "
        "Mark the strongest option with recommended=true to set a default. "
        "Returns the chosen option label and description as JSON, or the free-text answer as JSON."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to present to the user.",
            },
            "options": {
                "type": "array",
                "description": "List of options for the user to choose from (2-4 items).",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Short option identifier shown to the user.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Explanation of this option and its trade-offs.",
                        },
                        "recommended": {
                            "type": "boolean",
                            "description": (
                                "True if this is the recommended default. "
                                "At most one option should be recommended."
                            ),
                        },
                    },
                    "required": ["label", "description"],
                },
                "minItems": 0,
                "maxItems": 4,
            },
        },
        "required": ["question"],
    }

    def __init__(self, on_ask_user: Callable[[str, list[dict]], str]) -> None:
        self._on_ask_user = on_ask_user

    def run(self, question: str, options: list[dict] | None = None) -> str:
        options = options or []
        chosen = self._on_ask_user(question, options)
        matched_desc = next(
            (o.get("description", "") for o in options if o["label"] == chosen),
            None,
        )
        if matched_desc is not None:
            return json.dumps({"chosen": chosen, "description": matched_desc})
        return json.dumps({"answer": chosen})
