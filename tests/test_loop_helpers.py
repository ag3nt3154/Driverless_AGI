"""Verify module-level loop helpers are importable from agent._loop_helpers.

Why this matters: these helpers build the loop's continuation logic, system
prompt, and reload notifications. The extraction must be a pure move.
"""
from agent._loop_helpers import (
    CONTINUE_PROMPT,
    _build_wiki_index_context,
    _extract_reasoning,
    _format_reload_notification,
)


def test_continue_prompt_loaded_from_disk():
    assert "write_handoff" in CONTINUE_PROMPT or len(CONTINUE_PROMPT) > 0


def test_format_reload_notification_no_changes():
    result = _format_reload_notification(3, set(), set(), [])
    assert "3 skill(s) loaded" in result
    assert "No changes detected" in result


def test_format_reload_notification_with_changes():
    result = _format_reload_notification(
        4, {"new-skill"}, {"old-skill"}, [("bad/path.md", "boom")]
    )
    assert "New: new-skill" in result
    assert "Removed: old-skill" in result
    assert "Error: bad/path.md — boom" in result


def test_extract_reasoning_from_attr():
    from types import SimpleNamespace

    msg = SimpleNamespace(reasoning_content="thinking hard", model_extra={})
    assert _extract_reasoning(msg) == "thinking hard"


def test_extract_reasoning_from_model_extra():
    from types import SimpleNamespace

    msg = SimpleNamespace(reasoning_content=None, model_extra={"reasoning": "deep thought"})
    assert _extract_reasoning(msg) == "deep thought"


def test_build_wiki_index_context_missing(tmp_path):
    assert _build_wiki_index_context(tmp_path) is None


def test_reexport_from_agent_loop():
    from agent import loop as loop_mod

    assert loop_mod.CONTINUE_PROMPT is CONTINUE_PROMPT
