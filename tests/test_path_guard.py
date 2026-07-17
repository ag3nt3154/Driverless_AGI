"""tests/test_path_guard.py — Unit tests for validate_path() sandboxing."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools._path_guard import PathNotAllowedError, validate_path


class TestSandboxModeDisabled:
    def test_none_allowed_roots_permits_any_path(self, tmp_path):
        target = tmp_path / "anything.txt"
        target.write_text("x", encoding="utf-8")
        result = validate_path(target, None)
        assert result == target.resolve()


class TestDirectoryRoots:
    def test_path_inside_allowed_directory_is_permitted(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        target = root / "sub" / "file.txt"
        target.parent.mkdir()
        target.write_text("x", encoding="utf-8")

        result = validate_path(target, [root])

        assert result == target.resolve()

    def test_path_outside_all_roots_raises(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        outside = tmp_path / "elsewhere" / "file.txt"
        outside.parent.mkdir()
        outside.write_text("x", encoding="utf-8")

        with pytest.raises(PathNotAllowedError):
            validate_path(outside, [root])

    def test_parent_traversal_escape_is_rejected(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        escape_target = root / ".." / "secret.txt"
        (tmp_path / "secret.txt").write_text("x", encoding="utf-8")

        with pytest.raises(PathNotAllowedError):
            validate_path(escape_target, [root])

    def test_multiple_roots_matches_second_root(self, tmp_path):
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        root_a.mkdir()
        root_b.mkdir()
        target = root_b / "file.txt"
        target.write_text("x", encoding="utf-8")

        result = validate_path(target, [root_a, root_b])

        assert result == target.resolve()

    def test_error_message_lists_all_allowed_roots(self, tmp_path):
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        root_a.mkdir()
        root_b.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("x", encoding="utf-8")

        with pytest.raises(PathNotAllowedError) as exc_info:
            validate_path(outside, [root_a, root_b])

        message = str(exc_info.value)
        assert str(root_a.resolve()) in message
        assert str(root_b.resolve()) in message


class TestExactFileRoots:
    def test_exact_file_root_permits_only_that_file(self, tmp_path):
        allowed_file = tmp_path / "plan.md"
        allowed_file.write_text("plan", encoding="utf-8")

        result = validate_path(allowed_file, [allowed_file])

        assert result == allowed_file.resolve()

    def test_exact_file_root_rejects_sibling_file(self, tmp_path):
        allowed_file = tmp_path / "plan.md"
        allowed_file.write_text("plan", encoding="utf-8")
        sibling = tmp_path / "other.md"
        sibling.write_text("other", encoding="utf-8")

        with pytest.raises(PathNotAllowedError):
            validate_path(sibling, [allowed_file])

    def test_exact_file_root_rejects_directory_containing_it(self, tmp_path):
        allowed_file = tmp_path / "plan.md"
        allowed_file.write_text("plan", encoding="utf-8")
        other = tmp_path / "notes.md"
        other.write_text("notes", encoding="utf-8")

        # A directory of the same parent is not itself allowed just because
        # a sibling file within it is on the allow-list.
        with pytest.raises(PathNotAllowedError):
            validate_path(other, [allowed_file])
