from __future__ import annotations

from agent._board_files import MAX_ATTACHMENT
from pyside_gui.board_runtime import check_user_file, should_render_inline, validate_user_files


def test_validate_user_files_accepts_four_regular_files(tmp_path):
    paths = []
    for index in range(4):
        path = tmp_path / f"{index}.txt"
        path.write_text("x", encoding="utf-8")
        paths.append(path)
    assert validate_user_files(paths) == (paths, [])


def test_validate_user_files_rejects_too_many_before_stat(tmp_path):
    accepted, errors = validate_user_files([tmp_path / str(i) for i in range(5)])
    assert accepted == []
    assert errors == ["Attach at most 4 files."]


def test_should_render_inline_resolves_only_main_agent_meme(tmp_path):
    meme = tmp_path / "wave.png"
    post = {"author": "main_12345678", "meme": "wave"}
    assert should_render_inline(post, post["author"], {"wave": meme}) == meme
    assert should_render_inline(post, "main_deadbeef", {"wave": meme}) is None
    assert should_render_inline({**post, "meme": "missing"}, post["author"], {}) is None


def test_check_user_file_reports_each_refusal(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("x", encoding="utf-8")
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    large = tmp_path / "large.bin"
    large.write_bytes(b"x" * (MAX_ATTACHMENT + 1))
    assert check_user_file(good) is None
    assert "1 byte through 10 MB" in check_user_file(empty)
    assert "1 byte through 10 MB" in check_user_file(large)
    assert "1 byte through 10 MB" in check_user_file(tmp_path)
    assert "unavailable" in check_user_file(tmp_path / "missing.txt")


def test_validate_user_files_reports_checker_errors(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("x", encoding="utf-8")
    missing = tmp_path / "missing.txt"
    assert validate_user_files([good, missing]) == ([good], [check_user_file(missing)])
