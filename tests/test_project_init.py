"""Initialization creates a slim briefing and the task-artifact folder, never overwriting."""
import pytest

from agent._loop_helpers import project_slug
from agent.cli_utils import _cmd_init

EXPECTED = {"AGENTS.md", "wiki/tasks/README.md"}


def _files(root):
    return {p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_file() and ".dagi" not in p.relative_to(root).parts}


def test_init_creates_exactly_briefing_and_tasks_readme(tmp_path):
    _cmd_init(tmp_path)
    assert _files(tmp_path) == EXPECTED
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    for heading in ("## Overview", "## Rules", "## Commands & Environment", "## Memory"):
        assert heading in agents
    assert "memory-query" in agents and "memory-add" in agents
    assert f"projects\\{project_slug(tmp_path)}\\" in agents
    for name in ("skills", "workflow", "self-review", "logs"):
        assert (tmp_path / ".dagi" / name).is_dir()


def test_init_repeat_preserves_all_file_bytes(tmp_path):
    _cmd_init(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    _cmd_init(tmp_path)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("content", [b"", b"User-maintained knowledge\n"])
def test_init_preserves_legacy_wiki_and_agents(tmp_path, content):
    legacy = [tmp_path / "AGENTS.md", tmp_path / "wiki" / "index.md",
              tmp_path / "wiki" / "notes" / "x.md", tmp_path / "legacy-store" / "r.txt"]
    for p in legacy:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    _cmd_init(tmp_path)
    assert all(p.read_bytes() == content for p in legacy)
    assert (tmp_path / "wiki" / "tasks" / "README.md").is_file()


def test_init_keeps_selected_root_cwd_and_git_state(tmp_path):
    from pathlib import Path

    project = tmp_path / "selected"
    project.mkdir()
    # A minimal existing Git repository avoids creating commits during this test.
    git_dir = project / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "objects").mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/existing\n")
    before = {p.relative_to(git_dir): p.read_bytes()
              for p in git_dir.rglob("*") if p.is_file()}
    cwd = Path.cwd()
    _cmd_init(project)
    assert Path.cwd() == cwd
    assert (project / "wiki" / "tasks" / "README.md").is_file()
    assert not (tmp_path / "wiki").exists()
    assert before == {p.relative_to(git_dir): p.read_bytes()
                      for p in git_dir.rglob("*") if p.is_file()}
