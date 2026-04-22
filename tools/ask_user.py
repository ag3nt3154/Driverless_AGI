from __future__ import annotations

import json
from typing import Callable

from agent.base_tool import BaseTool


class AskUserTool(BaseTool):
    name = "ask_user"
    description = (
        "Pause planning and present the user with a question and a list of options. "
        "Use during user-initiated plan mode to resolve ambiguities, choose between approaches, "
        "or confirm architectural decisions. "
        "Provide 2-4 concrete options; mark the strongest with recommended=true. "
        "The user picks one option, or the recommended option (or first if none marked) is "
        "chosen automatically after a 5-minute timeout. "
        "Returns the chosen option label and description as JSON."
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
                "minItems": 2,
                "maxItems": 4,
            },
        },
        "required": ["question", "options"],
    }

    def __init__(self, on_ask_user: Callable[[str, list[dict]], str]) -> None:
        self._on_ask_user = on_ask_user

    def run(self, question: str, options: list[dict]) -> str:
        chosen_label = self._on_ask_user(question, options)
        chosen_desc = next(
            (o.get("description", "") for o in options if o["label"] == chosen_label),
            "",
        )
        return json.dumps({"chosen": chosen_label, "description": chosen_desc})
