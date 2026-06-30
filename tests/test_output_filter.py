"""tests/test_output_filter.py — Unit tests for filter_tool_output()."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest

from tools.output_filter import filter_tool_output

_RESERVE = 100   # 100 tokens → threshold chars = 400


class TestPassThrough:
    """Results below the token threshold pass through unchanged."""

    def test_short_string_returned_unchanged(self, tmp_path):
        result = "hello world"
        ctx, full = filter_tool_output(result, _RESERVE, tmp_path)
        assert ctx == "hello world"
        assert full == "hello world"

    def test_short_string_no_file_written(self, tmp_path):
        filter_tool_output("short", _RESERVE, tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_short_list_returned_unchanged(self, tmp_path):
        result = [{"type": "text", "text": "hi"}]
        ctx, full = filter_tool_output(result, _RESERVE, tmp_path)
        assert ctx == result          # original list, not serialised
        assert full == "__list__:" + json.dumps(result)

    def test_one_below_threshold_passes_through(self, tmp_path):
        # threshold is strict <, so _RESERVE - 1 tokens passes through
        result = "x" * (_RESERVE * 4 - 1)
        ctx, full = filter_tool_output(result, _RESERVE, tmp_path)
        assert ctx == result

    def test_at_threshold_is_filtered(self, tmp_path):
        # exactly _RESERVE tokens (>= threshold) fires the filter
        result = "x" * (_RESERVE * 4)
        ctx, _ = filter_tool_output(result, _RESERVE, tmp_path)
        assert isinstance(ctx, str)
        assert "OUTPUT TRUNCATED" in ctx


class TestFiltering:
    """Results at or above the token threshold are filtered."""

    def _large(self):
        """A string that exceeds _RESERVE tokens."""
        return "y" * (_RESERVE * 4 + 1)

    def test_full_str_is_always_complete(self, tmp_path):
        large = self._large()
        _, full = filter_tool_output(large, _RESERVE, tmp_path)
        assert full == large

    def test_context_result_is_str_when_filtered(self, tmp_path):
        ctx, _ = filter_tool_output(self._large(), _RESERVE, tmp_path)
        assert isinstance(ctx, str)

    def test_context_result_contains_preview(self, tmp_path):
        large = self._large()
        ctx, _ = filter_tool_output(large, _RESERVE, tmp_path)
        preview_chars = (_RESERVE // 2) * 4
        assert large[:preview_chars] in ctx

    def test_context_result_contains_truncation_marker(self, tmp_path):
        ctx, _ = filter_tool_output(self._large(), _RESERVE, tmp_path)
        assert "OUTPUT TRUNCATED" in ctx

    def test_context_result_contains_file_path(self, tmp_path):
        ctx, _ = filter_tool_output(self._large(), _RESERVE, tmp_path)
        assert str(tmp_path) in ctx

    def test_temp_file_written_with_full_content(self, tmp_path):
        large = self._large()
        filter_tool_output(large, _RESERVE, tmp_path)
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == large

    def test_temp_file_has_correct_prefix_and_suffix(self, tmp_path):
        filter_tool_output(self._large(), _RESERVE, tmp_path)
        files = list(tmp_path.iterdir())
        assert files[0].name.startswith("tool_output_")
        assert files[0].name.endswith(".txt")

    def test_large_list_is_filtered(self, tmp_path):
        # Build a list whose serialised form exceeds the threshold
        large_list = [{"type": "text", "text": "z" * (_RESERVE * 4 + 100)}]
        ctx, full = filter_tool_output(large_list, _RESERVE, tmp_path)
        assert isinstance(ctx, str)
        assert "OUTPUT TRUNCATED" in ctx
        assert full == "__list__:" + json.dumps(large_list)

    def test_context_result_mentions_read_tool(self, tmp_path):
        ctx, _ = filter_tool_output(self._large(), _RESERVE, tmp_path)
        assert "read" in ctx.lower()


class TestErrorHandling:
    """Disk errors fail open — return original result, no crash."""

    def test_mkdir_failure_returns_original(self, tmp_path):
        bad_dir = tmp_path / "no_perms"
        with patch("tools.output_filter.Path.mkdir", side_effect=OSError("permission denied")):
            large = "z" * (_RESERVE * 4 + 1)
            ctx, full = filter_tool_output(large, _RESERVE, bad_dir)
        assert ctx == large   # unfiltered pass-through
        assert full == large

    def test_write_failure_returns_original(self, tmp_path):
        with patch("tools.output_filter.Path.write_text", side_effect=OSError("disk full")):
            large = "z" * (_RESERVE * 4 + 1)
            ctx, full = filter_tool_output(large, _RESERVE, tmp_path)
        assert ctx == large

    def test_zero_reserve_tokens_skips_filtering(self, tmp_path):
        large = "z" * 9999
        ctx, full = filter_tool_output(large, reserve_tokens=0, temp_dir=tmp_path)
        assert ctx == large
        assert list(tmp_path.iterdir()) == []
