"""tests/test_config_editor.py — comment-preserving config.yaml editing."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent.config_editor import (
    ConfigConflictError,
    ConfigDocument,
    ConfigParseError,
    file_hash,
)

FIXTURES = Path(__file__).parent / "fixtures" / "config_editor"


def _copy_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_bytes((FIXTURES / "config.yaml").read_bytes())
    return path


def test_round_trip_is_byte_identical(tmp_path):
    src = (FIXTURES / "config.yaml").read_text(encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(src, encoding="utf-8")
    assert ConfigDocument.load(path).text() == src


def test_unedited_save_leaves_file_bytes_unchanged(tmp_path):
    """Save must not rewrite line endings or content of an untouched file."""
    path = _copy_fixture(tmp_path)
    original = path.read_bytes()
    ConfigDocument.load(path).save()
    assert path.read_bytes() == original


def test_crlf_file_round_trips_on_save(tmp_path):
    lf = (FIXTURES / "config.yaml").read_bytes().replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    path = tmp_path / "config.yaml"
    path.write_bytes(crlf)
    doc = ConfigDocument.load(path)
    assert doc.text() == lf.decode("utf-8")
    doc.save()
    assert path.read_bytes() == crlf
    doc.set("context_window", 1234)
    doc.save()
    assert b"context_window: 1234\r\n" in path.read_bytes()
    assert b"\n" not in path.read_bytes().replace(b"\r\n", b"")


def test_set_scalar_keeps_commented_alternatives(tmp_path):
    path = _copy_fixture(tmp_path)
    doc = ConfigDocument.load(path)
    doc.set("default_model", "local_model")
    out = doc.text()
    assert "default_model: local_model" in out
    assert "# default_model: minimax-2.7-openrouter" in out
    assert out.count("\n") == path.read_text(encoding="utf-8").count("\n")


def test_set_scalar_changes_only_that_line(tmp_path):
    path = _copy_fixture(tmp_path)
    original = path.read_text(encoding="utf-8").splitlines()
    doc = ConfigDocument.load(path)
    doc.set("default_model", "x")
    changed = [
        (a, b) for a, b in zip(original, doc.text().splitlines()) if a != b
    ]
    assert changed == [("default_model: deepseek-flash", "default_model: x")]


def test_set_scalar_keeps_inline_comment(tmp_path):
    path = _copy_fixture(tmp_path)
    doc = ConfigDocument.load(path)
    doc.set("sandbox_mode", True)
    assert (
        "sandbox_mode: true      # true = file tools have no path restrictions"
        in doc.text()
    )
    assert doc.get("sandbox_mode") is True


def test_get_dotted_and_default(tmp_path):
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    assert doc.get("services.message_board.url") == "http://127.0.0.1:8765"
    assert doc.get("context_window") == 200000
    assert doc.get("services.nope.url", "d") == "d"
    assert doc.get("context_window.deeper", "d") == "d"
    assert doc.get("missing") is None


def test_nested_set_existing_and_create(tmp_path):
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    doc.set("services.message_board.url", "http://10.0.0.2:9000")
    doc.set("services.other.port.number", 5)
    assert doc.get("services.message_board.url") == "http://10.0.0.2:9000"
    assert doc.get("services.other.port.number") == 5
    out = doc.text()
    # Comments within the services block survive.
    assert "# `bind` is used only by `python message_board.py`" in out
    assert 'url: "http://10.0.0.2:9000"' in out or "url: http://10.0.0.2:9000" in out
    reparsed = ConfigDocument.from_text(out, doc.path, doc.base_hash)
    assert reparsed.get("services.other.port.number") == 5


def test_set_none_deletes_key(tmp_path):
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    doc.set("services.message_board.bind", None)
    assert doc.get("services.message_board.bind") is None
    assert "bind:" not in doc.text().split("message_board:")[1].split("tools:")[0]
    doc.set("reserve_tokens", None)
    assert "reserve_tokens: 16384" not in doc.text()
    assert "# reserve_tokens: 10000" in doc.text()
    # Deleting an absent key is a no-op.
    doc.set("services.nope.x", None)
    assert doc.get("services.nope") is None


def _removed_lines(before: str, after: str) -> list[str]:
    import difflib

    return [
        line[1:]
        for line in difflib.ndiff(before.splitlines(), after.splitlines())
        if line.startswith(("- ", "+ "))
    ]


def test_delete_keeps_comment_lines_that_follow_the_key(tmp_path):
    """ruamel attaches following comments to the deleted key; they must survive."""
    path = _copy_fixture(tmp_path)
    original = path.read_text(encoding="utf-8")
    for key, line in [
        ("default_model", " default_model: deepseek-flash"),
        ("reserve_tokens", " reserve_tokens: 16384"),
        ("null_response_retries", " null_response_retries: 5"),
        ("memory_root", ' memory_root: "G:\\\\My Drive\\\\black_grimoire"'),
    ]:
        doc = ConfigDocument.load(path)
        doc.set(key, None)
        assert _removed_lines(original, doc.text()) == [line], key
        ConfigDocument.from_text(doc.text(), path, None)  # still valid YAML


def test_delete_first_nested_key_keeps_siblings(tmp_path):
    path = _copy_fixture(tmp_path)
    original = path.read_text(encoding="utf-8")
    doc = ConfigDocument.load(path)
    doc.set("services.message_board.url", None)
    assert _removed_lines(original, doc.text()) == ['     url: "http://127.0.0.1:8765"']


def test_deleting_last_nested_key_prunes_empty_maps(tmp_path):
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    doc.set("services.message_board.url", None)
    doc.set("services.message_board.bind", None)
    out = doc.text()
    assert "services:" not in out and "{}" not in out
    assert doc.get("services") is None
    assert "# Central memory store" in out
    ConfigDocument.from_text(out, doc.path, None)


def test_new_keys_append_without_displacing_comments(tmp_path):
    path = _copy_fixture(tmp_path)
    original = path.read_text(encoding="utf-8")
    doc = ConfigDocument.load(path)
    doc.set("services.other.port", 5)
    doc.set("worker_model", "w")
    out = doc.text()
    assert _removed_lines(original, out) == [
        "   other:", "     port: 5", " worker_model: w",
    ]
    # The nested key lands inside `services`, before `tools:`.
    assert out.index("  other:\n    port: 5\n") < out.index("tools:")
    assert out.endswith("worker_model: w\n")


def test_string_replacement_keeps_quote_style(tmp_path):
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    doc.set("memory_root", "D:\\data")
    assert 'memory_root: "D:\\\\data"' in doc.text()
    assert doc.get("memory_root") == "D:\\data"


def test_set_through_scalar_raises(tmp_path):
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    with pytest.raises(TypeError):
        doc.set("context_window.inner", 1)


def test_parse_error_carries_line(tmp_path):
    with pytest.raises(ConfigParseError) as exc:
        ConfigDocument.from_text("a: 1\nb: [1, 2\nc: 3\n", tmp_path / "c.yaml", None)
    assert exc.value.line is not None and exc.value.line >= 2
    assert exc.value.message


def test_non_mapping_root_is_parse_error(tmp_path):
    with pytest.raises(ConfigParseError):
        ConfigDocument.from_text("- a\n- b\n", tmp_path / "c.yaml", None)


def test_empty_text_is_empty_document(tmp_path):
    doc = ConfigDocument.from_text("", tmp_path / "c.yaml", None)
    assert doc.get("anything") is None
    doc.set("a.b", 1)
    assert doc.get("a.b") == 1


def test_missing_file_loads_empty(tmp_path):
    path = tmp_path / "config.yaml"
    doc = ConfigDocument.load(path)
    assert doc.base_hash is None
    assert doc.get("default_model") is None
    doc.set("default_model", "m1")
    new_hash = doc.save()
    assert path.read_text(encoding="utf-8") == "default_model: m1\n"
    assert new_hash == doc.base_hash == file_hash(path)


def test_file_hash(tmp_path):
    path = tmp_path / "x.yaml"
    assert file_hash(path) is None
    path.write_bytes(b"a: 1\n")
    assert file_hash(path) == hashlib.sha256(b"a: 1\n").hexdigest()


def test_load_records_base_hash(tmp_path):
    path = _copy_fixture(tmp_path)
    assert ConfigDocument.load(path).base_hash == file_hash(path)


def test_save_refuses_when_file_changed_on_disk(tmp_path):
    path = _copy_fixture(tmp_path)
    doc = ConfigDocument.load(path)
    path.write_text(path.read_text(encoding="utf-8") + "\n# external\n", encoding="utf-8")
    doc.set("context_window", 1000)
    with pytest.raises(ConfigConflictError):
        doc.save()
    assert "context_window: 1000" not in path.read_text(encoding="utf-8")
    doc.save(force=True)
    assert "context_window: 1000" in path.read_text(encoding="utf-8")


def test_save_refuses_when_file_appeared(tmp_path):
    path = tmp_path / "config.yaml"
    doc = ConfigDocument.load(path)
    path.write_text("a: 1\n", encoding="utf-8")
    doc.set("b", 2)
    with pytest.raises(ConfigConflictError):
        doc.save()


def test_save_with_explicit_expected_hash(tmp_path):
    path = _copy_fixture(tmp_path)
    doc = ConfigDocument.load(path)
    path.write_text("a: 1\n", encoding="utf-8")
    doc.set("context_window", 1000)
    doc.save(expected_hash=file_hash(path))
    assert "context_window: 1000" in path.read_text(encoding="utf-8")


def test_save_updates_base_hash_and_allows_second_save(tmp_path):
    path = _copy_fixture(tmp_path)
    doc = ConfigDocument.load(path)
    doc.set("context_window", 1000)
    h = doc.save()
    assert h == doc.base_hash == file_hash(path)
    doc.set("context_window", 2000)
    doc.save()
    assert "context_window: 2000" in path.read_text(encoding="utf-8")


def test_atomic_save_leaves_no_tmp(tmp_path):
    path = _copy_fixture(tmp_path)
    doc = ConfigDocument.load(path)
    doc.set("context_window", 1000)
    doc.save()
    assert not path.with_suffix(".yaml.tmp").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.yaml"]


def test_from_text_keeps_given_base_hash(tmp_path):
    path = _copy_fixture(tmp_path)
    doc = ConfigDocument.from_text("a: 1\n", path, "abc")
    assert doc.base_hash == "abc"
    assert doc.path == path


def test_no_qt_import():
    import agent.config_editor as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "import PySide" not in src and "from PySide" not in src


def test_pruning_emptied_map_keeps_following_comments(tmp_path):
    doc = ConfigDocument.from_text("a:\n  x: 1\n# outer\nb: 3\n", tmp_path / "c.yaml", None)
    doc.set("a.x", None)
    assert doc.text() == "# outer\nb: 3\n"


def test_pruning_emptied_map_moves_comments_to_previous_sibling(tmp_path):
    text = "k: 0\na:\n  m:\n    x: 1  # gone\n# outer\nb: 3\n"
    doc = ConfigDocument.from_text(text, tmp_path / "c.yaml", None)
    doc.set("a.m.x", None)
    assert doc.text() == "k: 0\n# outer\nb: 3\n"


def test_new_container_value_keeps_trailing_comment_after_block(tmp_path):
    doc = ConfigDocument.from_text("a: 1\n# trailing\n", tmp_path / "c.yaml", None)
    doc.set("z", ["p"])
    assert doc.text() == "a: 1\nz:\n  - p\n# trailing\n"
    doc = ConfigDocument.from_text("a: 1\n# trailing\n", tmp_path / "c.yaml", None)
    doc.set("z", {"q": 1, "r": [2]})
    assert doc.text() == "a: 1\nz:\n  q: 1\n  r:\n    - 2\n# trailing\n"


def test_failed_replace_removes_tmp_and_reraises(tmp_path, monkeypatch):
    import agent.config_editor as mod

    path = _copy_fixture(tmp_path)
    original = path.read_bytes()
    doc = ConfigDocument.load(path)
    doc.set("context_window", 1000)

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        doc.save()
    assert not path.with_suffix(".yaml.tmp").exists()
    assert path.read_bytes() == original
    assert doc.base_hash == file_hash(path)


def test_save_creates_missing_parent_dir(tmp_path):
    path = tmp_path / "nested" / ".dagi" / "config.yaml"
    doc = ConfigDocument.load(path)
    doc.set("default_model", "m1")
    doc.save()
    assert path.read_text(encoding="utf-8") == "default_model: m1\n"


# ── Comment-toggle list items ──────────────────────────────────────────────


def _fixture_text() -> str:
    return (FIXTURES / "config.yaml").read_bytes().decode("utf-8").replace("\r\n", "\n")


FIXTURE_TOOLS = [
    "read", "grep", "find", "write", "edit", "copy",
    "bash", "code", "tmux_bash",
    "enter_plan_mode", "update_task_status", "set_active_plan", "check_active_plan",
    "ask_user", "run_worker", "review_work", "web_research", "explore_files",
    "read_large_file", "extend_subagent_timeout",
    "switch_model",
    "skill", "run_skill_script", "reload_skills",
    "web_search", "web_fetch",
    "read_board", "post_board", "fetch_attachment",
    "show_file",
]


def _doc(text: str, tmp_path: Path) -> ConfigDocument:
    return ConfigDocument.from_text(text, tmp_path / "c.yaml", "h0")


def test_toggle_bash_round_trips(tmp_path):
    path = _copy_fixture(tmp_path)
    original = _fixture_text()
    doc = ConfigDocument.load(path)
    doc.set_item_enabled("tools", "bash", False)
    assert "  # - bash" in doc.text()
    assert "bash" not in doc.get("tools")
    doc.set_item_enabled("tools", "bash", True)
    assert doc.text() == original


def test_disable_changes_only_that_line(tmp_path):
    original = _fixture_text()
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    doc.set_item_enabled("tools", "bash", False)
    assert _removed_lines(original, doc.text()) == [
        "   - bash                    # Run arbitrary shell commands",
        "   # - bash                    # Run arbitrary shell commands",
    ]


def test_disabling_first_entry_under_header_keeps_header(tmp_path):
    original = _fixture_text()
    for name, header in [("bash", "  # ── Shell tools ──"), ("read", "  # ── File tools ──")]:
        doc = ConfigDocument.load(_copy_fixture(tmp_path))
        doc.set_item_enabled("tools", name, False)
        out = doc.text()
        assert header in out
        assert out.count("\n") == original.count("\n")
        lines = out.splitlines()
        idx = next(i for i, l in enumerate(lines) if l.startswith(f"  # - {name} "))
        assert lines[idx - 1].startswith(header)


def test_list_items_lists_fixture_tools_in_order(tmp_path):
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    assert doc.list_items("tools") == [(n, True) for n in FIXTURE_TOOLS]
    assert doc.list_items("disabled_tools") == [("memory_refresh", True)]


def test_disabled_entry_stays_listed_at_same_position(tmp_path):
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    doc.set_item_enabled("tools", "bash", False)
    items = doc.list_items("tools")
    assert [n for n, _ in items] == FIXTURE_TOOLS
    assert items[FIXTURE_TOOLS.index("bash")] == ("bash", False)
    assert all(enabled for n, enabled in items if n != "bash")
    assert doc.get("tools") == [n for n in FIXTURE_TOOLS if n != "bash"]


def test_disabled_tools_toggles_the_same_way(tmp_path):
    original = _fixture_text()
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    doc.set_item_enabled("disabled_tools", "memory_refresh", False)
    out = doc.text()
    assert "  # - memory_refresh      # Built for the retired memory layout" in out
    assert not doc.get("disabled_tools")
    assert doc.list_items("disabled_tools") == [("memory_refresh", False)]
    doc.set_item_enabled("disabled_tools", "memory_refresh", True)
    assert doc.text() == original
    assert doc.get("disabled_tools") == ["memory_refresh"]


def test_enable_unknown_name_appends_at_end_of_block(tmp_path):
    original = _fixture_text()
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    doc.set_item_enabled("tools", "new_tool", True)
    out = doc.text()
    assert _removed_lines(original, out) == ["   - new_tool"]
    assert out.index("  - show_file") < out.index("  - new_tool\n") < out.index("sandbox_mode:")
    assert doc.get("tools")[-1] == "new_tool"
    assert doc.list_items("tools")[-1] == ("new_tool", True)


def test_append_uses_existing_item_indentation(tmp_path):
    doc = _doc("tools:\n    - a\nb: 1\n", tmp_path)
    doc.set_item_enabled("tools", "c", True)
    assert doc.get("tools") == ["a", "c"]
    doc = _doc("tools:\n- a\nb: 1\n", tmp_path)
    doc.set_item_enabled("tools", "c", True)
    assert doc.get("tools") == ["a", "c"]


def test_append_goes_after_commented_last_entry(tmp_path):
    doc = _doc("tools:\n  - a\n  # - b\n# about c\nc: 1\n", tmp_path)
    doc.set_item_enabled("tools", "x", True)
    assert doc.text() == "tools:\n  - a\n  # - b\n  - x\n# about c\nc: 1\n"


def test_enable_creates_missing_key(tmp_path):
    doc = _doc("a: 1\n", tmp_path)
    doc.set_item_enabled("tools", "x", True)
    assert doc.text() == "a: 1\ntools:\n  - x\n"
    assert doc.get("tools") == ["x"]
    doc = _doc("", tmp_path)
    doc.set_item_enabled("tools", "x", True)
    assert doc.get("tools") == ["x"]


@pytest.mark.parametrize("line", ["tools: null", "tools:", "tools: ~"])
def test_empty_or_null_key(tmp_path, line):
    doc = _doc(f"{line}\nb: 1\n", tmp_path)
    assert doc.list_items("tools") == []
    doc.set_item_enabled("tools", "x", True)
    assert doc.text() == "tools:\n  - x\nb: 1\n"
    assert doc.get("tools") == ["x"]


def test_null_key_keeps_inline_comment(tmp_path):
    doc = _doc("tools: null   # all tools\nb: 1\n", tmp_path)
    doc.set_item_enabled("tools", "x", True)
    assert doc.get("tools") == ["x"]
    assert "# all tools" in doc.text()


def test_all_commented_block(tmp_path):
    doc = _doc("tools:\n  # - a\n  # - b   # note\nc: 1\n", tmp_path)
    assert doc.get("tools") is None
    assert doc.list_items("tools") == [("a", False), ("b", False)]
    doc.set_item_enabled("tools", "b", True)
    assert doc.text() == "tools:\n  # - a\n  - b   # note\nc: 1\n"
    assert doc.get("tools") == ["b"]


def test_trailing_top_level_comments_are_not_entries(tmp_path):
    doc = _doc("tools:\n  - a\n# - b\n# note\nc: 1\n", tmp_path)
    assert doc.list_items("tools") == [("a", True)]


def test_section_headers_are_not_entries(tmp_path):
    doc = _doc("tools:\n  # ── Hdr ──\n  - a\n  # plain note\nc: 1\n", tmp_path)
    assert doc.list_items("tools") == [("a", True)]


def test_noop_when_already_in_state(tmp_path):
    original = _fixture_text()
    doc = ConfigDocument.load(_copy_fixture(tmp_path))
    doc.set_item_enabled("tools", "bash", True)
    doc.set_item_enabled("tools", "absent_tool", False)
    doc.set_item_enabled("missing_key", "x", False)
    assert doc.text() == original
    assert doc.get("missing_key") is None


def test_nested_key_of_same_name_is_ignored(tmp_path):
    doc = _doc("svc:\n  tools:\n    - a\n", tmp_path)
    assert doc.list_items("tools") == []
    doc.set_item_enabled("tools", "x", True)
    assert doc.get("svc.tools") == ["a"]
    assert doc.get("tools") == ["x"]


def test_flow_style_list(tmp_path):
    doc = _doc("tools: [a, b]\nc: 1\n", tmp_path)
    assert doc.list_items("tools") == [("a", True), ("b", True)]
    with pytest.raises(ValueError, match="flow"):
        doc.set_item_enabled("tools", "a", False)


def test_toggle_keeps_base_hash_path_and_crlf(tmp_path):
    lf = (FIXTURES / "config.yaml").read_bytes().replace(b"\r\n", b"\n")
    path = tmp_path / "config.yaml"
    path.write_bytes(lf.replace(b"\n", b"\r\n"))
    doc = ConfigDocument.load(path)
    h = doc.base_hash
    doc.set_item_enabled("tools", "bash", False)
    assert doc.base_hash == h and doc.path == path
    doc.save()
    data = path.read_bytes()
    assert b"  # - bash" in data
    assert b"\n" not in data.replace(b"\r\n", b"")


@pytest.mark.parametrize("commented", ["  #   - b", "  #- b", "  #\t- b"])
def test_uncomment_puts_dash_at_hash_column(tmp_path, commented):
    doc = _doc(f"tools:\n  - a\n{commented}\nc: 1\n", tmp_path)
    assert doc.list_items("tools") == [("a", True), ("b", False)]
    doc.set_item_enabled("tools", "b", True)
    assert doc.text() == "tools:\n  - a\n  - b\nc: 1\n"
    assert doc.get("tools") == ["a", "b"]


def test_quoted_entries(tmp_path):
    text = "tools:\n  - \"bash\"\n  - 'x'   # note\nc: 1\n"
    doc = _doc(text, tmp_path)
    assert doc.list_items("tools") == [("bash", True), ("x", True)]
    doc.set_item_enabled("tools", "bash", False)
    assert doc.text() == "tools:\n  # - \"bash\"\n  - 'x'   # note\nc: 1\n"
    assert doc.get("tools") == ["x"]
    assert doc.list_items("tools") == [("bash", False), ("x", True)]
    doc.set_item_enabled("tools", "x", True)  # no-op, no duplicate
    doc.set_item_enabled("tools", "bash", True)
    assert doc.text() == text
    doc.set_item_enabled("tools", "x", False)
    assert doc.list_items("tools") == [("bash", True), ("x", False)]


def test_mismatched_quotes_are_not_entries(tmp_path):
    doc = _doc("tools:\n  # - \"bash'\nc: 1\n", tmp_path)
    assert doc.list_items("tools") == []


def test_commented_only_block_locks_indent(tmp_path):
    doc = _doc("tools:\n  # - a\n# - b\nc: 1\n", tmp_path)
    assert doc.list_items("tools") == [("a", False)]
    doc.set_item_enabled("tools", "b", True)
    assert doc.text() == "tools:\n  # - a\n  - b\n# - b\nc: 1\n"


def test_non_block_scalar_value_cannot_toggle(tmp_path):
    doc = _doc("tools: all\nc: 1\n", tmp_path)
    with pytest.raises(ValueError, match="not a block list"):
        doc.set_item_enabled("tools", "a", True)


def test_invalid_item_name_rejected(tmp_path):
    doc = _doc("tools:\n  - a\n", tmp_path)
    with pytest.raises(ValueError):
        doc.set_item_enabled("tools", "bad name: x", True)
