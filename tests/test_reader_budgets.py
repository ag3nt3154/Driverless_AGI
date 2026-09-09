"""tests/test_reader_budgets.py — Budget arithmetic for the large-file reader.

Tests resolve_reader_limits, allocate_sections, estimate_*, require_* and
ReaderCapacityError. No provider calls; no filesystem writes beyond tmp_path.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tools.output_filter import estimate_tool_output
from tools.read._budgets import (
    ReaderCapacityError,
    ReaderLimits,
    SummaryAllocation,
    allocate_sections,
    estimate_reader_request,
    estimate_reader_text,
    require_context_fit,
    require_parent_fit,
    resolve_reader_limits,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(
    *,
    context_window: int = 200_000,
    reserve_tokens: int = 16_384,
    keep_recent_tokens: int = 20_000,
    max_output_tokens: int | None = None,
    max_continuations: int = 10,
    request_kwargs: dict | None = None,
) -> tuple[object, dict]:
    """Return a minimal AgentConfig-like object and request_kwargs dict."""
    cfg = SimpleNamespace(
        context_window=context_window,
        reserve_tokens=reserve_tokens,
        keep_recent_tokens=keep_recent_tokens,
        max_output_tokens=max_output_tokens,
        max_continuations=max_continuations,
    )
    return cfg, request_kwargs or {}


def _chunk(estimated_tokens: int = 100) -> object:
    return SimpleNamespace(estimated_tokens=estimated_tokens)


# ---------------------------------------------------------------------------
# estimate_tool_output (shared F estimator)
# ---------------------------------------------------------------------------

class TestEstimateToolOutput:
    """Verify the shared //4 estimator used as F in parent-fit checks."""

    def test_string_4p_minus_1_below_p(self):
        P = 300
        text = "x" * (4 * P - 1)
        assert estimate_tool_output(text) < P

    def test_string_4p_at_threshold(self):
        P = 300
        text = "x" * (4 * P)
        assert estimate_tool_output(text) == P

    def test_string_4p_plus_4_above_p(self):
        P = 300
        text = "x" * (4 * P + 4)   # 1204 // 4 == 301 > 300
        assert estimate_tool_output(text) > P

    def test_list_serialised_correctly(self):
        import json
        items = [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]
        # list serializes to __list__:<json>
        serialised = "__list__:" + json.dumps(items)
        expected = len(serialised) // 4
        assert estimate_tool_output(items) == expected

    def test_unicode_cjk_counted_by_chars_not_bytes(self):
        # CJK code points are 3 bytes UTF-8 but ONE character
        text = "你好世界" * 100   # 400 chars, 1200 bytes
        assert estimate_tool_output(text) == 400 // 4  # 100

    def test_empty_string_returns_zero(self):
        assert estimate_tool_output("") == 0

    def test_combining_marks_counted_as_chars(self):
        # combining mark is U+0301 — one code point, two UTF-8 bytes
        text = "á" * 200   # 400 code points
        assert estimate_tool_output(text) == 400 // 4


# ---------------------------------------------------------------------------
# resolve_reader_limits
# ---------------------------------------------------------------------------

class TestResolveReaderLimits:
    def test_basic_derivation(self):
        cfg, rk = _cfg(context_window=6000, reserve_tokens=700)
        limits = resolve_reader_limits(300, cfg, request_kwargs=rk)

        assert limits.parent_reserve == 300
        assert limits.context_window == 6000
        assert limits.output_reserve == 700          # O = R when no cap
        assert limits.estimator_margin == math.ceil(700 / 8)
        assert limits.max_repairs == 10

    def test_max_output_tokens_tightens_O(self):
        cfg, rk = _cfg(context_window=6000, reserve_tokens=700, max_output_tokens=200)
        limits = resolve_reader_limits(300, cfg, request_kwargs=rk)
        assert limits.output_reserve == 200          # tightened by max_output_tokens

    def test_client_cap_max_tokens_tightens_O(self):
        cfg, rk = _cfg(context_window=6000, reserve_tokens=700, request_kwargs={"max_tokens": 150})
        limits = resolve_reader_limits(300, cfg, request_kwargs=rk)
        assert limits.output_reserve == 150

    def test_client_cap_max_completion_tokens_tightens_O(self):
        cfg, rk = _cfg(context_window=6000, reserve_tokens=700)
        limits = resolve_reader_limits(300, cfg, request_kwargs={"max_completion_tokens": 120})
        assert limits.output_reserve == 120

    def test_tightest_cap_wins(self):
        # R=700, max_output_tokens=200, client cap=150 → O=150
        cfg, rk = _cfg(context_window=6000, reserve_tokens=700, max_output_tokens=200)
        limits = resolve_reader_limits(300, cfg, request_kwargs={"max_tokens": 150})
        assert limits.output_reserve == 150

    def test_max_output_tokens_larger_than_R_does_not_widen(self):
        # max_output_tokens=9999 > R=700 → O=700
        cfg, rk = _cfg(context_window=6000, reserve_tokens=700, max_output_tokens=9999)
        limits = resolve_reader_limits(300, cfg, request_kwargs=rk)
        assert limits.output_reserve == 700

    def test_nonpositive_parent_reserve_raises(self):
        cfg, rk = _cfg(context_window=6000, reserve_tokens=700)
        with pytest.raises(ReaderCapacityError):
            resolve_reader_limits(0, cfg, request_kwargs=rk)

    def test_negative_parent_reserve_raises(self):
        cfg, rk = _cfg(context_window=6000, reserve_tokens=700)
        with pytest.raises(ReaderCapacityError):
            resolve_reader_limits(-1, cfg, request_kwargs=rk)

    def test_reserve_equals_context_raises(self):
        cfg, rk = _cfg(context_window=1000, reserve_tokens=1000)
        with pytest.raises(ValueError, match="less than context_window"):
            resolve_reader_limits(300, cfg, request_kwargs=rk)

    def test_reserve_exceeds_context_raises(self):
        cfg, rk = _cfg(context_window=500, reserve_tokens=700)
        with pytest.raises(ValueError, match="less than context_window"):
            resolve_reader_limits(300, cfg, request_kwargs=rk)

    def test_zero_context_window_raises(self):
        cfg, rk = _cfg(context_window=0, reserve_tokens=700)
        with pytest.raises(ValueError, match="context_window must be positive"):
            resolve_reader_limits(300, cfg, request_kwargs=rk)

    def test_margin_derived_from_reserve(self):
        # ceil(700/8) = 88
        cfg, rk = _cfg(context_window=6000, reserve_tokens=700)
        limits = resolve_reader_limits(300, cfg, request_kwargs=rk)
        assert limits.estimator_margin == math.ceil(700 / 8)

    def test_each_boundary_independent(self):
        """Changing C only should not affect O or M."""
        cfg_a, rk = _cfg(context_window=6000, reserve_tokens=700, max_output_tokens=200)
        cfg_b, _  = _cfg(context_window=12000, reserve_tokens=700, max_output_tokens=200)
        la = resolve_reader_limits(300, cfg_a, request_kwargs=rk)
        lb = resolve_reader_limits(300, cfg_b, request_kwargs=rk)
        assert la.output_reserve == lb.output_reserve
        assert la.estimator_margin == lb.estimator_margin
        assert lb.context_window == 12000


# ---------------------------------------------------------------------------
# estimate_reader_request
# ---------------------------------------------------------------------------

class TestEstimateReaderRequest:
    def test_returns_byte_count_of_json(self):
        import json
        req = {"model": "test", "messages": [{"role": "user", "content": "hello"}]}
        expected = len(json.dumps(req, ensure_ascii=False).encode("utf-8"))
        assert estimate_reader_request(req) == expected

    def test_unicode_counted_by_bytes(self):
        req = {"content": "你好"}
        import json
        expected = len(json.dumps(req, ensure_ascii=False).encode("utf-8"))
        assert estimate_reader_request(req) == expected

    def test_larger_request_gives_larger_estimate(self):
        small = {"messages": [{"role": "user", "content": "hi"}]}
        large = {"messages": [{"role": "user", "content": "x" * 10000}]}
        assert estimate_reader_request(large) > estimate_reader_request(small)


# ---------------------------------------------------------------------------
# estimate_reader_text
# ---------------------------------------------------------------------------

class TestEstimateReaderText:
    def test_matches_chars_div_4(self):
        text = "a" * 400
        assert estimate_reader_text(text) == 100

    def test_consistent_with_estimate_tool_output(self):
        text = "hello world"
        assert estimate_reader_text(text) == estimate_tool_output(text)

    def test_empty(self):
        assert estimate_reader_text("") == 0


# ---------------------------------------------------------------------------
# require_context_fit
# ---------------------------------------------------------------------------

class TestRequireContextFit:
    def _make_limits(self, C=10000, O=500, M=100):
        return ReaderLimits(
            parent_reserve=300,
            context_window=C,
            output_reserve=O,
            estimator_margin=M,
            max_repairs=3,
        )

    def test_fits_does_not_raise(self):
        req = {"messages": [{"role": "user", "content": "hi"}]}
        limits = self._make_limits(C=10000)
        # E(req) is tiny; 10000 context window easily fits
        require_context_fit(req, limits)

    def test_oversized_raises(self):
        huge_content = "x" * 100_000
        req = {"messages": [{"role": "user", "content": huge_content}]}
        limits = self._make_limits(C=10000, O=500, M=100)
        with pytest.raises(ReaderCapacityError) as exc_info:
            require_context_fit(req, limits)
        err = exc_info.value
        assert err.required_tokens > err.available_tokens
        assert err.recommendation == ReaderCapacityError.LARGER_MODEL


# ---------------------------------------------------------------------------
# allocate_sections
# ---------------------------------------------------------------------------

class TestAllocateSections:
    def test_empty_chunks_returns_empty(self):
        result = allocate_sections((), available_chars=1000, minimum_refs=())
        assert result == ()

    def test_single_chunk_gets_all_prose(self):
        chunks = (_chunk(100),)
        allocs = allocate_sections(chunks, available_chars=500, minimum_refs=())
        assert len(allocs) == 1
        assert allocs[0] == 500

    def test_proportional_split(self):
        # chunks 100 and 300 tokens → should get 1/4 and 3/4 of prose
        chunks = (_chunk(100), _chunk(300))
        allocs = allocate_sections(chunks, available_chars=400, minimum_refs=())
        assert len(allocs) == 2
        assert allocs[0] + allocs[1] == 400
        # First chunk should be smaller
        assert allocs[0] < allocs[1]

    def test_minimum_refs_subtracted_first(self):
        refs = ("ref_chunk_0", "ref_chunk_1")
        ref_chars = sum(len(r) for r in refs)
        chunks = (_chunk(100), _chunk(100))
        allocs = allocate_sections(chunks, available_chars=400, minimum_refs=refs)
        assert sum(allocs) == 400 - ref_chars

    def test_remainder_goes_to_last_chunk(self):
        # Three equal chunks with available_chars=10 (not divisible by 3)
        chunks = (_chunk(1), _chunk(1), _chunk(1))
        allocs = allocate_sections(chunks, available_chars=10, minimum_refs=())
        assert sum(allocs) == 10

    def test_zero_available_gives_zeros(self):
        chunks = (_chunk(100), _chunk(100))
        allocs = allocate_sections(chunks, available_chars=0, minimum_refs=())
        assert all(a == 0 for a in allocs)


# ---------------------------------------------------------------------------
# require_parent_fit
# ---------------------------------------------------------------------------

class TestRequireParentFit:
    def test_small_text_does_not_raise(self):
        P = 300
        text = "x" * (4 * P - 5)  # just below threshold
        require_parent_fit(text, P)  # must not raise

    def test_at_threshold_raises(self):
        P = 300
        text = "x" * (4 * P)      # estimate_tool_output == P >= P → must raise
        with pytest.raises(ReaderCapacityError) as exc_info:
            require_parent_fit(text, P)
        assert exc_info.value.recommendation == ReaderCapacityError.NARROW_RANGE

    def test_above_threshold_raises(self):
        P = 300
        text = "x" * (4 * P + 100)
        with pytest.raises(ReaderCapacityError):
            require_parent_fit(text, P)

    def test_error_has_all_fields(self):
        P = 100
        text = "x" * 500
        with pytest.raises(ReaderCapacityError) as exc_info:
            require_parent_fit(text, P)
        err = exc_info.value
        assert err.required_tokens > 0
        assert err.available_tokens >= 0
        assert err.recommendation in (
            ReaderCapacityError.NARROW_RANGE,
            ReaderCapacityError.LARGER_MODEL,
            ReaderCapacityError.FEWER_PAGES,
        )


# ---------------------------------------------------------------------------
# ReaderCapacityError string format
# ---------------------------------------------------------------------------

class TestReaderCapacityError:
    def test_str_contains_all_fields(self):
        err = ReaderCapacityError(
            required_tokens=5000,
            available_tokens=3000,
            recommendation=ReaderCapacityError.LARGER_MODEL,
        )
        s = str(err)
        assert "5,000" in s
        assert "3,000" in s
        assert ReaderCapacityError.LARGER_MODEL in s

    def test_recommendation_constants(self):
        assert ReaderCapacityError.NARROW_RANGE == "narrow the selected range"
        assert ReaderCapacityError.LARGER_MODEL == "configure a larger context_window model"
        assert ReaderCapacityError.FEWER_PAGES  == "reduce the number of selected pages"


# ---------------------------------------------------------------------------
# Config loader integration: truthiness fix and new fields
# ---------------------------------------------------------------------------

class TestConfigLoaderNewFields:
    """Verify that config_loader correctly loads max_output_tokens and
    use_legacy_reader, and that the truthiness bug fix works for token fields."""

    def _resolve(self, tmp_path, yaml_text: str, model_id: str = "m1"):
        import yaml as _yaml
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml_text, encoding="utf-8")
        from agent.config_loader import resolve_model_config
        import os
        env_patch = {"TEST_KEY": "sk-test"}
        import unittest.mock as mock
        with mock.patch.dict(os.environ, env_patch):
            return resolve_model_config(
                model_id=model_id,
                config_path=cfg_file,
                project_path=None,
            )

    def test_max_output_tokens_loaded_from_model_entry(self, tmp_path):
        yaml_text = """
default_model: m1
models:
  m1:
    model: test/model
    api_key_env: TEST_KEY
    max_output_tokens: 200
"""
        cfg = self._resolve(tmp_path, yaml_text)
        assert cfg.max_output_tokens == 200

    def test_max_output_tokens_loaded_from_top_level(self, tmp_path):
        yaml_text = """
default_model: m1
max_output_tokens: 512
models:
  m1:
    model: test/model
    api_key_env: TEST_KEY
"""
        cfg = self._resolve(tmp_path, yaml_text)
        assert cfg.max_output_tokens == 512

    def test_max_output_tokens_absent_is_none(self, tmp_path):
        yaml_text = """
default_model: m1
models:
  m1:
    model: test/model
    api_key_env: TEST_KEY
"""
        cfg = self._resolve(tmp_path, yaml_text)
        assert cfg.max_output_tokens is None

    def test_use_legacy_reader_loaded(self, tmp_path):
        yaml_text = """
default_model: m1
use_legacy_reader: true
models:
  m1:
    model: test/model
    api_key_env: TEST_KEY
"""
        cfg = self._resolve(tmp_path, yaml_text)
        assert cfg.use_legacy_reader is True

    def test_use_legacy_reader_defaults_false(self, tmp_path):
        yaml_text = """
default_model: m1
models:
  m1:
    model: test/model
    api_key_env: TEST_KEY
"""
        cfg = self._resolve(tmp_path, yaml_text)
        assert cfg.use_legacy_reader is False

    def test_explicit_zero_context_window_not_overridden_by_raw(self, tmp_path):
        """Truthiness fix: entry context_window: 0 must not fall back to raw default."""
        yaml_text = """
default_model: m1
context_window: 128000
models:
  m1:
    model: test/model
    api_key_env: TEST_KEY
    context_window: 0
"""
        cfg = self._resolve(tmp_path, yaml_text)
        # Before the fix this would be 128000; after the fix it should be 0.
        assert cfg.context_window == 0

    def test_worker_model_carries_max_output_tokens(self, tmp_path):
        yaml_text = """
default_model: m1
worker_model: w1
models:
  m1:
    model: test/model
    api_key_env: TEST_KEY
  w1:
    model: worker/model
    api_key_env: TEST_KEY
    context_window: 6000
    reserve_tokens: 700
    max_output_tokens: 200
"""
        cfg = self._resolve(tmp_path, yaml_text)
        assert cfg.worker_config is not None
        assert cfg.worker_config.max_output_tokens == 200
        assert cfg.worker_config.context_window == 6000
        assert cfg.worker_config.reserve_tokens == 700
