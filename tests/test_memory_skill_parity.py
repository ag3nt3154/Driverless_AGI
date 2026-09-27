"""The DAGI memory skills are full copies of the Claude Code ones (decision: full copies)."""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLAUDE = Path.home() / ".claude" / "skills"


@pytest.mark.parametrize("name", ["memory-add", "memory-query"])
def test_memory_skill_matches_claude_copy(name):
    claude = CLAUDE / name / "SKILL.md"
    if not claude.exists():
        pytest.skip("Claude Code skills not installed on this machine")
    ours = REPO / ".dagi" / "skills" / name / "SKILL.md"
    assert ours.read_bytes() == claude.read_bytes(), f"{name} drifted — re-copy it"
