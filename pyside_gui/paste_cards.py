"""Long-paste cards: big pastes become an inline token in the composer.

Pasting ``LONG_LINES``+ lines or ``LONG_CHARS``+ characters inserts a token
such as ``[Pasted text #1 · 412 lines]`` at the cursor instead of the text.
On submit each token is replaced by its text inside a ```` ```pasted ```` fence
(longer than any backtick run inside), so the model sees exactly where the
paste starts and ends, and the conversation pane can show it as a card.
"""
from __future__ import annotations

import re

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

from pyside_gui.theme import qcolor

LONG_LINES = 15
LONG_CHARS = 1500
FENCE_INFO = "pasted"

TOKEN_RE = re.compile(r"\[Pasted text #(\d+) · [\d,]+ lines?\]")


def is_long(text: str) -> bool:
    return len(text) >= LONG_CHARS or text.count("\n") + 1 >= LONG_LINES


def line_count(text: str) -> int:
    return text.rstrip("\n").count("\n") + 1


def make_token(number: int, text: str) -> str:
    lines = line_count(text)
    return f"[Pasted text #{number} · {lines:,} line{'s' if lines != 1 else ''}]"


def fence(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{FENCE_INFO}\n{text.rstrip(chr(10))}\n{ticks}"


def expand(text: str, pastes: dict[int, str]) -> str:
    """Replace every intact token with its fenced paste, on lines of its own.
    Tokens whose paste is unknown are left as typed."""
    out: list[str] = []
    last = 0
    for match in TOKEN_RE.finditer(text):
        paste = pastes.get(int(match.group(1)))
        if paste is None:
            continue
        before = text[last:match.start()]
        out.append(before)
        if before and not before.endswith("\n"):
            out.append("\n")
        out.append(fence(paste))
        rest = text[match.end():]
        if rest and not rest.startswith("\n"):
            out.append("\n")
        last = match.end()
    out.append(text[last:])
    return "".join(out)


def token_span(text: str, pos: int, *, inclusive_end: bool = True) -> tuple[int, int, int] | None:
    """``(start, end, number)`` of the token containing ``pos``.

    With ``inclusive_end`` a position right after the token still counts
    (Backspace there removes the whole token); otherwise a position right
    before it counts (Delete there)."""
    for match in TOKEN_RE.finditer(text):
        start, end = match.span()
        inside = start < pos <= end if inclusive_end else start <= pos < end
        if inside:
            return start, end, int(match.group(1))
    return None


class TokenHighlighter(QSyntaxHighlighter):
    """Shows paste tokens as link-coloured chips in the editor."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self._format = QTextCharFormat()
        self._format.setForeground(qcolor("link"))
        background = QColor(qcolor("link"))
        background.setAlphaF(0.14)
        self._format.setBackground(background)

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        for match in TOKEN_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._format)
