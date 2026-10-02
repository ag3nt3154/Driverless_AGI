"""tests/tui/test_system_breakdown.py — the sidebar must not charge one file twice.

Why this matters: running dagi inside its own repo makes dagi_root and project_path the
same directory, and `_system_breakdown` fetched `<root>/AGENTS.md` once per row. The rows
are summed into the sidebar's Total and the context bar, so the same file was billed
twice — a wrong context pressure reading, not a cosmetic one. (`_toks` measures decoded
characters, so this repo's 4,327-byte AGENTS.md reads as 1,057, not 1,081.)
"""
from tui.utils import _system_breakdown


def test_agents_md_not_double_counted_when_roots_match(tmp_path):
    (tmp_path / "AGENTS.md").write_text("a" * 400, encoding="utf-8")

    breakdown = _system_breakdown(tmp_path, tmp_path)

    assert breakdown["dagi/ag"] > 0
    assert breakdown["proj/ag"] == 0


def test_both_agents_md_counted_when_roots_differ(tmp_path):
    """Distinct roots are distinct files: both rows must stay non-zero."""
    dagi_root = tmp_path / "dagi"
    project = tmp_path / "proj"
    dagi_root.mkdir()
    project.mkdir()
    (dagi_root / "AGENTS.md").write_text("d" * 400, encoding="utf-8")
    (project / "AGENTS.md").write_text("p" * 400, encoding="utf-8")

    breakdown = _system_breakdown(dagi_root, project)

    assert breakdown["dagi/ag"] > 0
    assert breakdown["proj/ag"] > 0
