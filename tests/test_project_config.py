"""Tests for per-project config + prompt resolution."""
from __future__ import annotations

from pathlib import Path

import pytest


# ── Prompt resolution ────────────────────────────────────────────────────────

def test_load_main_system_prompt_falls_back_to_dagi_root(tmp_path):
    """When no project prompt exists, load from dagi root."""
    from agent.prompts import load_main_system_prompt
    dagi_root = Path(__file__).parent.parent
    # tmp_path has no .dagi/prompts/main_system.md
    result = load_main_system_prompt(dagi_root, tmp_path)
    # Should be the real dagi system prompt (non-empty, contains known marker)
    assert "<<END_OF_RESPONSE>>" in result or "<<TASK_END>>" in result


def test_load_main_system_prompt_uses_project_prompt_when_present(tmp_path):
    """When project has a main_system.md, it fully replaces the dagi root prompt."""
    from agent.prompts import load_main_system_prompt
    project_prompt_dir = tmp_path / ".dagi" / "prompts"
    project_prompt_dir.mkdir(parents=True)
    (project_prompt_dir / "main_system.md").write_text(
        "Project-specific system prompt.\n{tools_and_skills}\n", encoding="utf-8"
    )
    dagi_root = Path(__file__).parent.parent
    result = load_main_system_prompt(dagi_root, tmp_path)
    assert result == "Project-specific system prompt.\n{tools_and_skills}\n"


def test_load_soul_falls_back_to_dagi_root(tmp_path):
    """When no project soul exists, load from dagi root .dagi/prompts/soul.md."""
    from agent.prompts import load_soul
    dagi_root = Path(__file__).parent.parent
    result = load_soul(dagi_root, tmp_path)
    # Dagi root soul exists and is non-empty (content is intentionally not asserted)
    assert result is not None and len(result) > 0


def test_load_soul_uses_project_soul_when_present(tmp_path):
    """Project .dagi/prompts/soul.md overrides dagi root soul."""
    from agent.prompts import load_soul
    soul_dir = tmp_path / ".dagi" / "prompts"
    soul_dir.mkdir(parents=True)
    (soul_dir / "soul.md").write_text("Custom project persona.\n", encoding="utf-8")
    dagi_root = Path(__file__).parent.parent
    result = load_soul(dagi_root, tmp_path)
    assert result == "Custom project persona.\n"


def test_load_soul_returns_none_when_absent(tmp_path):
    """Returns None when neither project nor dagi root soul exists."""
    from agent.prompts import load_soul
    # Point dagi_root to tmp_path so neither soul exists
    result = load_soul(tmp_path, tmp_path)
    assert result is None
