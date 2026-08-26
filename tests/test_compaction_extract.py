"""Verify compaction helpers are importable and behave from agent._compaction.

Why this matters: compaction mutates the session surface atomically — the
step-collection and surface-index helpers must keep their exact semantics or
compaction will shadow the wrong nodes.
"""
from types import SimpleNamespace

from agent._compaction import (
    collect_steps,
    compact,
    compact_context,
    find_surface_index_for_step,
    log_compaction,
)


def _fake_log(pairs):
    """Fake SessionLog: events with seqs, one surface node per event."""
    events = [
        SimpleNamespace(seq=i * 10, data={"turn": t, "step": s})
        for i, (t, s) in enumerate(pairs)
    ]
    return SimpleNamespace(events=events, surface=SimpleNamespace(nodes=[e.seq for e in events]))


def test_collect_steps_dedupes_and_preserves_order():
    log = _fake_log([(1, 1), (1, 2), (1, 1), (2, 1)])
    assert collect_steps(log) == [(1, 1), (1, 2), (2, 1)]


def test_collect_steps_skips_events_without_turn_or_step():
    log = SimpleNamespace(
        events=[
            SimpleNamespace(seq=1, data={}),
            SimpleNamespace(seq=2, data={"turn": 3, "step": 1}),
        ],
        surface=SimpleNamespace(nodes=[1, 2]),
    )
    assert collect_steps(log) == [(3, 1)]


def test_find_surface_index_for_step_found():
    log = _fake_log([(1, 1), (1, 2), (2, 1)])
    assert find_surface_index_for_step(log, (1, 2)) == 1


def test_find_surface_index_for_step_raises_when_missing():
    import pytest

    log = _fake_log([(1, 1)])
    with pytest.raises(ValueError):
        find_surface_index_for_step(log, (9, 9))


def test_all_public_functions_importable():
    for fn in (compact, compact_context, log_compaction):
        assert callable(fn)
