from __future__ import annotations

from pyside_gui.board_runtime import should_render_inline


def test_should_render_inline_resolves_only_main_agent_meme(tmp_path):
    meme = tmp_path / "wave.png"
    post = {"author": "main_12345678", "meme": "wave"}
    assert should_render_inline(post, post["author"], {"wave": meme}) == meme
    assert should_render_inline(post, "main_deadbeef", {"wave": meme}) is None
    assert should_render_inline({**post, "meme": "missing"}, post["author"], {}) is None
