from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / ".dagi" / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt template from .dagi/prompts/<name>."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")
