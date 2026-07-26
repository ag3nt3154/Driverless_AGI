from __future__ import annotations

import json
import threading
from typing import Callable

from agent.base_tool import BaseTool


class AskUserTool(BaseTool):
    name = "ask_user"
    description = (
        "Pause and ask the user a question. Use to resolve ambiguity, choose between approaches, "
        "or collect feedback. Optionally provide 2-4 hint options (label+description+recommended); "
        "user always answers in free text. Set no_timeout=true to wait indefinitely; default "
        "auto-proceeds after session timeout using the recommended option. "
        "Returns {question, options, answer} as JSON."
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
                "description": "Hint options shown to user (2-4 items); user always answers in free text.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Short option label.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Explanation and trade-offs.",
                        },
                        "recommended": {
                            "type": "boolean",
                            "description": "True if recommended default (at most one).",
                        },
                    },
                    "required": ["label", "description"],
                },
                "minItems": 0,
                "maxItems": 4,
            },
            "no_timeout": {
                "type": "boolean",
                "description": "If true, wait indefinitely; default auto-proceeds after session timeout.",
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
