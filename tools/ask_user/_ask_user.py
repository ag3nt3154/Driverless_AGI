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
        "Optionally provide 2-4 options with labels, descriptions, and a recommended flag — "
        "these are displayed as hints, but the user always responds in free text. "
        "Set no_timeout=true to wait indefinitely for the user's answer. "
        "By default, auto-proceeds after the session timeout using the recommended option. "
        "Returns the original question, the full options list, and the user's verbatim answer as JSON."
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
                "description": (
                    "Optional hint options shown to the user (2-4 items). "
                    "The user always responds in free text regardless."
                ),
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
            "no_timeout": {
                "type": "boolean",
                "description": (
                    "If true, the terminal waits indefinitely for the user's answer. "
                    "If false (default), auto-proceeds after the session timeout."
                ),
            },
        },
        "required": ["question"],
    }

    def __init__(
        self,
        on_ask_user: Callable[[str, list[dict], float | None], str],
        timeout: int | None = 300,
    ) -> None:
        self._on_ask_user = on_ask_user
        self._timeout = timeout

    def _fallback(self, options: list[dict]) -> str:
        if not options:
            return "[no-response - timed out]"
        recommended = next((o["label"] for o in options if o.get("recommended")), None)
        return recommended if recommended is not None else options[0]["label"]

    def run(self, question: str, options: list[dict] | None = None, no_timeout: bool = False) -> str:
        options = options or []
        effective_timeout: float | None = None if no_timeout else self._timeout
        result: list[str] = []

        def _ask() -> None:
            result.append(self._on_ask_user(question, options, effective_timeout))

        t = threading.Thread(target=_ask, daemon=True)
        t.start()
        t.join(timeout=effective_timeout)

        answer = result[0] if result else self._fallback(options)
        return json.dumps({"question": question, "options": options, "answer": answer})
