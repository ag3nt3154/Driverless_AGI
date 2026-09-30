from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from agent import notepad_store
from agent.base_tool import BaseTool

MAX_CHARS = 20_000


class ReadNotepadTool(BaseTool):
    name = "read_notepad"
    description = (
        "Read the user's desktop-pet notepad: a global markdown scratch note "
        "(may contain $...$ / $$...$$ LaTeX math). Read-only."
    )
    _parameters = {"type": "object", "properties": {}}

    def __init__(
        self,
        on_flush: Callable[[], bool] | None = None,
        root: Path = notepad_store.NOTEPAD_DIR,
    ) -> None:
        self._on_flush = on_flush
        self._root = root

    def run(self) -> str:
        stale = ""
        if self._on_flush is not None:
            try:
                flushed = self._on_flush()
            except Exception:  # noqa: BLE001 - a GUI hiccup must not fail the read
                flushed = False
            if not flushed:
                stale = " — unsaved edits may be missing"

        text = notepad_store.read_text(self._root)
        if not text.strip():
            return f"Notepad is empty.{stale}"

        mtime = notepad_store.notepad_path(self._root).stat().st_mtime
        edited = datetime.fromtimestamp(mtime).isoformat(timespec="seconds")
        header = f"Notepad (last edited {edited}, {len(text)} chars{stale})"
        if len(text) > MAX_CHARS:
            text = (
                text[:MAX_CHARS]
                + f"\n\n[... truncated: showing {MAX_CHARS} of {len(text)} chars]"
            )
        return f"{header}\n\n{text}"
