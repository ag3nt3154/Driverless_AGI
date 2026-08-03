from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent.base_tool import BaseTool


def _list_emotes(emotes_dir: Path) -> list[str]:
    """Return sorted names of available .md emote files."""
    if not emotes_dir.is_dir():
        return []
    return sorted(p.stem for p in emotes_dir.glob("*.md"))


def pad_to_lines(text: str, n: int = 5) -> str:
    """Vertically center *text* within *n* lines by padding with blank lines.

    Content with fewer than *n* lines is centered (extra padding goes on the
    bottom when it can't be split evenly). Content with *n* or more lines is
    left untouched.
    """
    lines = text.splitlines()
    pad = n - len(lines)
    if pad <= 0:
        return text
    top = pad // 2
    bottom = pad - top
    return "\n".join([""] * top + lines + [""] * bottom)


class EmoteTool(BaseTool):
    name = "emote"

    def __init__(
        self,
        emotes_dir: Path,
        on_emote: Callable[[str, str, bool], None] | None = None,
    ) -> None:
        self._emotes_dir = emotes_dir
        self._on_emote = on_emote
        available = _list_emotes(emotes_dir)
        names = ", ".join(available) if available else "(none found)"
        self.description = (
            "Display an emote/emoticon on the sidebar. "
            "Pass a named emote to show its saved ASCII art, "
            "or pass any custom text (unicode faces, kaomoji, ASCII art) to display directly. "
            f"Named emotes: {names}"
        )

    _parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "A named emote (e.g. 'shrug', 'lenny', 'happy') "
                    "or any custom text/emoticon to display in the sidebar."
                ),
            }
        },
        "required": ["text"],
    }

    def _resolve(self, text: str) -> str:
        """If *text* matches a .md file in the emotes dir, return its content; else return *text* as-is."""
        path = self._emotes_dir / f"{text}.md"
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            raw = text
        return pad_to_lines(raw)

    def run(self, text: str) -> str:
        display = self._resolve(text)
        is_named = (self._emotes_dir / f"{text}.md").is_file()
        if self._on_emote:
            self._on_emote(text, display, is_named)
        return f"*{text}*" if is_named else f"Displaying: {display}"
