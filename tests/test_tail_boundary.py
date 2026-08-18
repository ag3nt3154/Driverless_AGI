"""Tests for step-based tail boundary computation."""
from __future__ import annotations

import pytest

from tools.compact._tail_boundary import compute_tail_boundary


class TestComputeTailBoundary:
    def test_keeps_recent_steps_by_token_budget(self):
        """Given 10 steps and budget for ~3 steps, keep the last 3."""
        steps = [(1, s) for s in range(10)]  # turn 1, steps 0-9
        boundary = compute_tail_boundary(
            steps=steps,
            prompt_tokens=10_000,
            keep_recent_tokens=3_000,
        )
        # avg = 10000/10 = 1000 tokens/step → floor(3000/1000) = 3 steps
        # tail starts at step index 7 (keeping steps 7, 8, 9)
        assert boundary.tail_start_index == 7
        assert boundary.keep_count == 3
        assert boundary.tail_steps == [(1, 7), (1, 8), (1, 9)]

    def test_floors_to_whole_steps(self):
        """Partial-step budget rounds down to whole steps."""
        steps = [(1, s) for s in range(5)]
        boundary = compute_tail_boundary(
            steps=steps,
            prompt_tokens=5_000,
            keep_recent_tokens=2_500,
        )
        # avg = 1000/step → floor(2500/1000) = 2
        assert boundary.keep_count == 2
        assert boundary.tail_start_index == 3

    def test_budget_covers_all_steps_returns_no_middle(self):
        """When the budget covers everything, no compaction needed."""
        steps = [(1, 0), (1, 1)]
        boundary = compute_tail_boundary(
            steps=steps,
            prompt_tokens=2_000,
            keep_recent_tokens=5_000,
        )
        assert boundary.keep_count == 2
        assert boundary.has_middle is False

    def test_budget_covers_zero_steps_keeps_at_least_one(self):
        """Always keep at least the current step."""
        steps = [(1, s) for s in range(10)]
        boundary = compute_tail_boundary(
            steps=steps,
            prompt_tokens=100_000,
            keep_recent_tokens=50,
        )
        assert boundary.keep_count >= 1
        assert boundary.tail_start_index <= len(steps) - 1

    def test_multi_turn_steps(self):
        """Steps spanning multiple turns are handled correctly."""
        steps = [(1, 0), (1, 1), (2, 0), (2, 1), (3, 0)]
        boundary = compute_tail_boundary(
            steps=steps,
            prompt_tokens=5_000,
            keep_recent_tokens=2_000,
        )
        # avg = 1000/step → floor(2000/1000) = 2 steps
        assert boundary.keep_count == 2
        assert boundary.tail_steps == [(2, 1), (3, 0)]

    def test_empty_steps_returns_no_middle(self):
        """No steps → nothing to compact."""
        boundary = compute_tail_boundary(
            steps=[],
            prompt_tokens=0,
            keep_recent_tokens=1000,
        )
        assert boundary.has_middle is False
