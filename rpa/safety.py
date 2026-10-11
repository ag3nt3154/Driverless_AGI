"""rpa/safety.py — per-app permission and sensitive-action confirmation (D5).

Deny-by-default: if nobody can answer (`ask is None`) or the session is
`autonomous`, every gate denies without calling `ask`. Options passed to `ask`
never carry a `recommended` key — a headless default handler (see
`agent/tools.py:_default_ask_user`) auto-picks the recommended option, which
would silently defeat this gate.
"""
from __future__ import annotations

import re
from typing import Callable

from rpa import RpaError
from rpa.model import Element, Root

__all__ = ["SafetyGate", "SafetyDenied", "is_sensitive"]

GATED_ACTIONS = frozenset(
    {"click", "double_click", "set_value", "type", "key", "select", "upload"}
)

_SENSITIVE_KEYWORDS = (
    "send",
    "submit",
    "delete",
    "remove",
    "pay",
    "purchase",
    "buy",
    "transfer",
    "post",
    "publish",
    "confirm",
    "sign out",
    "log out",
)

_SENSITIVE_PATTERNS = tuple(
    re.compile(r"\b" + r"\s+".join(re.escape(word) for word in keyword.split()) + r"\b")
    for keyword in _SENSITIVE_KEYWORDS
)


class SafetyDenied(RpaError):
    """A safety gate denied the action; `reason` says which gate and why."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def is_sensitive(element: Element) -> bool:
    """True if `element.name`, lower-cased, matches a sensitive keyword at a word boundary."""
    name = (element.name or "").lower()
    return any(pattern.search(name) for pattern in _SENSITIVE_PATTERNS)


class SafetyGate:
    """Per-session app permission and per-action sensitive-action confirmation.

    `ask(question, options) -> str` mirrors dagi's frontend callback: `options`
    is a list of `{"label", "description"}` dicts (never `"recommended"`), and
    the return value is the chosen label (free text is possible from a
    headless/model caller). Only an answer that equals the allow label exactly
    (case-insensitive, stripped) counts as allow; anything else — a deny
    label, free text, an empty string, or an exception raised by `ask` —
    denies.
    """

    def __init__(self, ask: Callable[[str, list[dict]], str] | None, autonomous: bool) -> None:
        self._ask = ask
        self._autonomous = autonomous
        self._allowed_apps: set[str] = set()

    def _allowed(self, question: str, options: list[dict], allow_label: str) -> bool:
        if self._ask is None or self._autonomous:
            return False
        try:
            answer = self._ask(question, options)
        except Exception:
            return False
        return isinstance(answer, str) and answer.strip().lower() == allow_label.strip().lower()

    def check_app(self, root: Root) -> None:
        """Ask once per `root.app` for this gate instance; deny is never remembered."""
        if root.app in self._allowed_apps:
            return
        question = f'Allow dagi to control "{root.app}" for this session?'
        options = [
            {"label": "Allow", "description": f'Let dagi control "{root.app}" for this session.'},
            {"label": "Deny", "description": "Do not allow this."},
        ]
        if not self._allowed(question, options, "Allow"):
            raise SafetyDenied(f'app permission denied for "{root.app}"')
        self._allowed_apps.add(root.app)

    def check_action(
        self,
        root: Root,
        element: Element,
        action: str,
        *,
        sensitive_flag: bool = False,
    ) -> None:
        """Ask for confirmation on a gated, sensitive action. Never remembered."""
        if action not in GATED_ACTIONS:
            return
        if not (sensitive_flag or is_sensitive(element)):
            return
        question = f'Confirm: {action} on {element.role} "{element.name}" in {root.app}?'
        options = [
            {"label": "Allow once", "description": "Perform this one action now."},
            {"label": "Deny", "description": "Do not perform this action."},
        ]
        if not self._allowed(question, options, "Allow once"):
            raise SafetyDenied(
                f'action confirmation denied for {action} on {element.role} "{element.name}"'
            )
