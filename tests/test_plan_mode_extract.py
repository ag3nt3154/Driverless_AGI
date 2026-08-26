"""Verify plan-mode lifecycle helpers are importable from agent._plan_mode.

Why this matters: entering/exiting/reloading plan mode swaps the tool registry
and model tier — the most state-mutating paths in the loop. The extraction
must preserve exact behaviour, including the empty-plan guard.
"""
import tempfile
from pathlib import Path

from agent._plan_mode import _is_plan_empty


def test_is_plan_empty_with_only_headings(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("# Plan\n\n## Context\n\n", encoding="utf-8")
    assert _is_plan_empty(p) is True


def test_is_plan_empty_with_content(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("# Plan\n\nSome real content here\n", encoding="utf-8")
    assert _is_plan_empty(p) is False


def test_is_plan_empty_with_unchecked_box_only(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("- [ ]\n", encoding="utf-8")
    assert _is_plan_empty(p) is True


def test_is_plan_empty_missing_file(tmp_path):
    assert _is_plan_empty(tmp_path / "nope.md") is True


def test_reexport_from_agent_loop():
    # Backward-compat contract: _is_plan_empty stays reachable via agent.loop.
    from agent import loop as loop_mod

    assert loop_mod._is_plan_empty is _is_plan_empty


def test_module_exists():
    import agent._plan_mode as pm

    for fn in (
        "handle_enter_plan_mode",
        "handle_exit_plan_mode",
        "handle_all_tasks_resolved",
        "rebuild_for_plan_mode",
        "rebuild_for_normal_mode",
        "rebuild_for_reload",
    ):
        assert callable(getattr(pm, fn)), fn
