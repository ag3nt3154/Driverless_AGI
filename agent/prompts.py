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


def load_main_system_prompt(dagi_root: Path, project_path: Path) -> str:
    """Load the main system prompt, preferring project-local over dagi root."""
    project_prompt = project_path / ".dagi" / "prompts" / "main_system.md"
    if project_prompt.exists():
        return project_prompt.read_text(encoding="utf-8")
    return load_prompt("main/main_system.md")


def load_soul(dagi_root: Path, project_path: Path) -> str | None:
    """Load the soul/persona, preferring project-local over dagi root. Returns None if absent."""
    project_soul = project_path / ".dagi" / "prompts" / "soul.md"
    if project_soul.exists():
        return project_soul.read_text(encoding="utf-8")
    dagi_soul = dagi_root / ".dagi" / "prompts" / "soul.md"
    if dagi_soul.exists():
        return dagi_soul.read_text(encoding="utf-8")
    return None
