"""Portable wiki bootstrap must preserve user data and stay in the selected root."""

import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / (
    "integrations/codex/skills/enter-workflow/scripts/init_wiki.py"
)
EXPECTED = {
    "wiki/index.md", "wiki/architecture.md", "wiki/workflows.md",
    "wiki/business-context.md", "wiki/decisions/index.md", "wiki/errors/index.md",
    "wiki/notes/index.md",
}


@pytest.fixture
def bootstrap():
    spec = importlib.util.spec_from_file_location("codex_init_wiki", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def test_empty_project_has_exact_navigable_wiki(tmp_path, bootstrap):
    before_cwd = Path.cwd()
    assert set(bootstrap.initialize_wiki(tmp_path)) == EXPECTED
    assert set(snapshot(tmp_path)) == EXPECTED
    assert Path.cwd() == before_cwd
    for page in tmp_path.rglob("*.md"):
        links = re.findall(r"\]\(([^)]+)\)", page.read_text(encoding="utf-8"))
        assert links, page
        assert all((page.parent / link).is_file() for link in links)


def test_partial_empty_existing_and_repeat_preserve_bytes(tmp_path, bootstrap):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/architecture.md").write_bytes(b"")
    (tmp_path / "wiki/workflows.md").write_bytes(b"custom\r\n\xff")
    (tmp_path / "AGENTS.md").write_bytes(b"standing instructions")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_bytes(b"ref: refs/heads/custom\n")
    before = snapshot(tmp_path)
    created = bootstrap.initialize_wiki(tmp_path)
    assert set(created) == EXPECTED - {"wiki/architecture.md", "wiki/workflows.md"}
    after = snapshot(tmp_path)
    assert all(after[path] == content for path, content in before.items())
    assert bootstrap.initialize_wiki(tmp_path) == []
    assert snapshot(tmp_path) == after
    assert not (tmp_path / ".dagi").exists()


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_invalid_root_fails(tmp_path, bootstrap, kind):
    root = tmp_path / kind
    if kind == "file":
        root.write_text("untouched")
    with pytest.raises(OSError, match=kind):
        bootstrap.initialize_wiki(root)
    assert not (root / "wiki").exists()


@pytest.mark.parametrize("collision", ["wiki/notes/index.md", "wiki/notes", "wiki"])
def test_preflight_rejects_collisions_before_writing(tmp_path, bootstrap, collision):
    target = tmp_path / collision
    target.parent.mkdir(parents=True, exist_ok=True)
    if collision.endswith(".md"):
        target.mkdir()
    else:
        target.write_text("preserve")
    before = snapshot(tmp_path)
    with pytest.raises(OSError, match="wiki"):
        bootstrap.initialize_wiki(tmp_path)
    assert snapshot(tmp_path) == before
    assert not (tmp_path / "wiki/index.md").exists()


def test_outside_directory_link_cannot_write(tmp_path, bootstrap):
    root, outside = tmp_path / "project", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "wiki"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"OS cannot create a directory symlink: {exc}")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
    try:
        with pytest.raises(OSError, match="outside|escape"):
            bootstrap.initialize_wiki(root)
        assert snapshot(outside) == {}
    finally:
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()


def test_cli_success_and_actionable_failure(tmp_path):
    success = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert success.returncode == 0, success.stderr
    assert "wiki/index.md" in success.stdout
    bad = tmp_path / "missing"
    failure = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(bad)],
        capture_output=True, text=True,
    )
    assert failure.returncode != 0
    assert str(bad) in failure.stderr


def test_containment_without_os_links(tmp_path, bootstrap):
    with pytest.raises(OSError, match="escape"):
        bootstrap._contained(tmp_path, tmp_path / ".." / "outside")


def test_permission_failure_is_not_treated_as_missing(tmp_path, bootstrap, monkeypatch):
    original = Path.lstat
    blocked = tmp_path / "wiki/notes/index.md"

    def denied(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError(f"Access denied: {path}")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", denied)
    with pytest.raises(PermissionError, match="notes"):
        bootstrap.initialize_wiki(tmp_path)
    assert snapshot(tmp_path) == {}


def test_partial_write_failure_reports_path_and_retry_preserves(tmp_path, bootstrap, monkeypatch):
    original = Path.open
    blocked = tmp_path / "wiki/workflows.md"

    def denied(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError("Access denied")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", denied)
        with pytest.raises(OSError, match="workflows.md"):
            bootstrap.initialize_wiki(tmp_path)
    before = snapshot(tmp_path)
    assert set(before) == {"wiki/index.md", "wiki/architecture.md"}
    assert set(bootstrap.initialize_wiki(tmp_path)) == EXPECTED - set(before)
    assert all(snapshot(tmp_path)[path] == content for path, content in before.items())


@pytest.mark.parametrize("regular", [True, False])
def test_exclusive_creation_race_checks_new_target(tmp_path, bootstrap, monkeypatch, regular):
    original = Path.open
    raced = tmp_path / "wiki/index.md"

    def competing_writer(path, mode="r", *args, **kwargs):
        if path == raced and mode == "x":
            if regular:
                with original(path, "wb") as stream:
                    stream.write(b"other initializer")
            else:
                path.mkdir()
            raise FileExistsError(str(path))
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", competing_writer)
    if regular:
        assert "wiki/index.md" not in bootstrap.initialize_wiki(tmp_path)
        assert raced.read_bytes() == b"other initializer"
    else:
        with pytest.raises(OSError, match="regular file"):
            bootstrap.initialize_wiki(tmp_path)
        assert not (tmp_path / "wiki/architecture.md").exists()
