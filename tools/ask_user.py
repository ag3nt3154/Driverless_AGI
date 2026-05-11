from __future__ import annotations

import json
import threading
from typing import Callable

from agent.base_tool import BaseTool


class AskUserTool(BaseTool):
    name = "ask_user"
    description = (
        "Pause and present the user with a question. "
        "Use to resolve ambiguities, choose between approaches, "
        "confirm architectural decisions, or collect free-text feedback. "
        "Optionally provide 2-4 concrete options; omit options entirely to ask a free-text question. "
        "Mark the strongest option with recommended=true to set a default. "
        "If the user does not respond within 5 minutes, the recommended option is chosen "
        "automatically (or '[no-response - timed out]' for free-text questions). "
        "Returns the chosen option label and description as JSON, or the answer as JSON."
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

    def __init__(self, on_ask_user: Callable[[str, list[dict]], str], timeout: int = 300) -> None:
        self._on_ask_user = on_ask_user
        self._timeout = timeout

    def _fallback(self, options: list[dict]) -> str:
        """Recommended option, first option, or timed-out sentinel for free-text."""
        if not options:
            return "[no-response - timed out]"
        recommended = next((o["label"] for o in options if o.get("recommended")), None)
        return recommended if recommended is not None else options[0]["label"]

    def run(self, question: str, options: list[dict] | None = None) -> str:
        options = options or []
        result: list[str] = []

        def _ask() -> None:
            result.append(self._on_ask_user(question, options))

        t = threading.Thread(target=_ask, daemon=True)
        t.start()
        t.join(timeout=self._timeout)

        chosen = result[0] if result else self._fallback(options)
        matched_desc = next(
            (o.get("description", "") for o in options if o["label"] == chosen),
            None,
        )
        if matched_desc is not None:
            return json.dumps({"chosen": chosen, "description": matched_desc})
        return json.dumps({"answer": chosen})
