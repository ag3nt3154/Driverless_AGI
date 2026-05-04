from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / ".dagi" / "prompts"
_SUBAGENTS_DIR = Path(__file__).parent.parent / ".dagi" / "subagents"


def load_prompt(name: str) -> str:
    """Load a prompt template from .dagi/prompts/<name>."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def load_subagent_prompt(name: str) -> str:
    """Load a system prompt from .dagi/subagents/<name>/prompt.md."""
    return (_SUBAGENTS_DIR / name / "prompt.md").read_text(encoding="utf-8")
