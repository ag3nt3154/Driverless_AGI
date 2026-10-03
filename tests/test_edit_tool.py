from pathlib import Path

from tools.edit import EditTool


def _make_tool(tmp_path):
    return EditTool(cwd=tmp_path, allowed_roots=[tmp_path])


def _write(tmp_path, name, content):
    f = tmp_path / name
    f.write_text(content, encoding="utf-8", newline="\n")
    return f


class TestBasicEdit:
    def test_replaces_unique_text(self, tmp_path):
        f = _write(tmp_path, "f.txt", "alpha\nbeta\ngamma")
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", oldText="beta", newText="BETA")

        assert f.read_text(encoding="utf-8") == "alpha\nBETA\ngamma"
        assert "Edited" in result

    def test_replaces_multiline_text(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a\nb\nc\nd")
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", oldText="b\nc", newText="X")

        assert f.read_text(encoding="utf-8") == "a\nX\nd"

    def test_writes_lf_only(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a\nb")
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", oldText="a", newText="X")

        assert b"\r\n" not in f.read_bytes()


class TestErrorHandling:
    def test_missing_text_reports_not_found(self, tmp_path):
        _write(tmp_path, "f.txt", "a\nb")
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", oldText="zzz", newText="X")

        assert "not found" in result

    def test_ambiguous_text_reports_count(self, tmp_path):
        f = _write(tmp_path, "f.txt", "dup\ndup")
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", oldText="dup", newText="X")

        assert "2 times" in result
        assert f.read_text(encoding="utf-8") == "dup\ndup"


class TestCRLFNormalization:
    def test_normalises_crlf_in_supplied_text(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a\nb\nc")
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", oldText="a\r\nb", newText="X")

        assert f.read_text(encoding="utf-8") == "X\nc"


class TestMultiEdit:
    """Several changes to one file in one call save a round trip each; a partial write would
    leave the file half-edited, so the batch is all-or-nothing."""

    def test_applies_all_edits_in_one_call(self, tmp_path):
        f = _write(tmp_path, "f.txt", "alpha\nbeta\ngamma")
        result = _make_tool(tmp_path).run(path="f.txt", edits=[
            {"oldText": "alpha", "newText": "ALPHA"},
            {"oldText": "gamma", "newText": "GAMMA"},
        ])
        assert f.read_text(encoding="utf-8") == "ALPHA\nbeta\nGAMMA"
        assert "2 edits" in result

    def test_later_edit_sees_earlier_result(self, tmp_path):
        f = _write(tmp_path, "f.txt", "one")
        _make_tool(tmp_path).run(path="f.txt", edits=[
            {"oldText": "one", "newText": "two"},
            {"oldText": "two", "newText": "three"},
        ])
        assert f.read_text(encoding="utf-8") == "three"

    def test_failure_writes_nothing_and_names_the_edit(self, tmp_path):
        f = _write(tmp_path, "f.txt", "alpha\nbeta")
        result = _make_tool(tmp_path).run(path="f.txt", edits=[
            {"oldText": "alpha", "newText": "ALPHA"},
            {"oldText": "missing", "newText": "x"},
        ])
        assert f.read_text(encoding="utf-8") == "alpha\nbeta"
        assert result.startswith("Error")
        assert "edit 2 of 2" in result and "not found" in result

    def test_ambiguous_edit_in_batch_writes_nothing(self, tmp_path):
        f = _write(tmp_path, "f.txt", "x x")
        result = _make_tool(tmp_path).run(path="f.txt", edits=[{"oldText": "x", "newText": "y"}])
        assert f.read_text(encoding="utf-8") == "x x"
        assert "edit 1 of 1" in result and "2 times" in result

    def test_both_forms_rejected(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a")
        result = _make_tool(tmp_path).run(
            path="f.txt", oldText="a", newText="b", edits=[{"oldText": "a", "newText": "c"}])
        assert result.startswith("Error") and f.read_text(encoding="utf-8") == "a"

    def test_neither_form_rejected(self, tmp_path):
        _write(tmp_path, "f.txt", "a")
        assert _make_tool(tmp_path).run(path="f.txt").startswith("Error")

    def test_malformed_edit_entry_rejected(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a")
        result = _make_tool(tmp_path).run(path="f.txt", edits=[{"oldText": "a"}])
        assert result.startswith("Error") and "edit 1 of 1" in result
        assert f.read_text(encoding="utf-8") == "a"

    def test_schema_advertises_edits_and_requires_only_path(self, tmp_path):
        params = _make_tool(tmp_path).schema()["function"]["parameters"]
        assert params["required"] == ["path"]
        assert params["properties"]["edits"]["type"] == "array"


class TestPlaceholderArguments:
    """Some providers fill every advertised parameter with an empty value; rejecting those
    calls as 'both forms' would cost the round trip multi-edit exists to save."""

    def test_empty_edits_list_with_single_form_applies(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a")
        result = _make_tool(tmp_path).run(path="f.txt", oldText="a", newText="b", edits=[])
        assert f.read_text(encoding="utf-8") == "b" and result.startswith("Edited")

    def test_empty_single_fields_with_edits_list_applies(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a")
        _make_tool(tmp_path).run(
            path="f.txt", oldText="", newText="", edits=[{"oldText": "a", "newText": "b"}])
        assert f.read_text(encoding="utf-8") == "b"

    def test_edits_sent_as_json_string_is_parsed(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a")
        _make_tool(tmp_path).run(path="f.txt", edits='[{"oldText": "a", "newText": "b"}]')
        assert f.read_text(encoding="utf-8") == "b"

    def test_empty_newtext_still_deletes_in_single_form(self, tmp_path):
        f = _write(tmp_path, "f.txt", "keep drop")
        _make_tool(tmp_path).run(path="f.txt", oldText=" drop", newText="")
        assert f.read_text(encoding="utf-8") == "keep"

    def test_single_form_messages_unchanged(self, tmp_path):
        _write(tmp_path, "f.txt", "x x")
        result = _make_tool(tmp_path).run(path="f.txt", oldText="x", newText="y")
        assert result == f"Error: oldText found 2 times in {tmp_path / 'f.txt'} — must be unique"

    def test_single_item_batch_grammar(self, tmp_path):
        _write(tmp_path, "f.txt", "a")
        result = _make_tool(tmp_path).run(path="f.txt", edits=[{"oldText": "a", "newText": "b"}])
        assert result.endswith("(1 edit)")
