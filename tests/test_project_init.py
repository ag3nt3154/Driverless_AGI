"""Initialization must preserve user knowledge and the selected workspace."""
import re

import pytest

from agent.cli_utils import _cmd_init


WIKI_PATHS = (
    "index.md", "architecture.md", "workflows.md", "business-context.md",
    "decisions/index.md", "errors/index.md", "notes/index.md",
)


def test_init_preserves_even_empty_existing_knowledge(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    page = wiki / "architecture.md"
    page.write_bytes(b"")
    _cmd_init(tmp_path)
    assert page.read_bytes() == b""
    assert (wiki / "index.md").is_file()
    assert not (tmp_path / "dagi-memory").exists()


def test_init_repeat_preserves_all_file_bytes(tmp_path):
    _cmd_init(tmp_path)
    before = {p.relative_to(tmp_path): p.read_bytes()
              for p in tmp_path.rglob("*") if p.is_file()}
    _cmd_init(tmp_path)
    after = {p.relative_to(tmp_path): p.read_bytes()
             for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_init_creates_navigable_wiki_and_operational_directories(tmp_path):
    _cmd_init(tmp_path)
    for relative in WIKI_PATHS:
        page = tmp_path / "wiki" / relative
        assert page.is_file()
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", page.read_text()):
            assert (page.parent / target).is_file(), (relative, target)
    for name in ("skills", "workflow", "self-review", "logs"):
        assert (tmp_path / ".dagi" / name).is_dir()
    assert (tmp_path / "AGENTS.md").is_file()


@pytest.mark.parametrize("content", [b"", b"User-maintained knowledge\n"])
def test_init_preserves_existing_agents_wiki_and_legacy_tree(tmp_path, content):
    paths = [tmp_path / "AGENTS.md", tmp_path / "dagi-memory" / "raw" / "source.txt"]
    paths.extend(tmp_path / "wiki" / relative for relative in WIKI_PATHS)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    _cmd_init(tmp_path)
    assert all(path.read_bytes() == content for path in paths)


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
    assert (project / "wiki" / "index.md").is_file()
    assert not (tmp_path / "wiki").exists()
    assert before == {p.relative_to(git_dir): p.read_bytes()
                      for p in git_dir.rglob("*") if p.is_file()}
