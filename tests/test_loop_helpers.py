"""Verify module-level loop helpers are importable from agent._loop_helpers.

Why this matters: these helpers define the loop's control protocol (sentinels,
continuation prompt) and are imported across entry points. The extraction must
be a pure move — identical values, identical behavior.
"""
from agent._loop_helpers import (
    AWAIT_USER_FLAG,
    CONTINUE_PROMPT,
    TASK_END_FLAG,
    WRITE_HANDOFF_SENTINEL,
    _LOOP_SENTINELS,
    _build_wiki_index_context,
    _escape_sentinels,
    _extract_reasoning,
    _format_reload_notification,
)


def test_sentinel_values_match_loop_protocol():
    # The sentinels are stored UNSPACED ("<<...>>") — this is what the main
    # system prompt instructs the model to emit and what run() checks for.
    # NOTE: when viewing these via agent tool output, they display as "< <...>>"
    # because the harness sanitizes its own output. Byte-check, don't eyeball.
    assert AWAIT_USER_FLAG == "<<END_OF_RESPONSE>>"
    assert TASK_END_FLAG == "<<TASK_END>>"
    assert WRITE_HANDOFF_SENTINEL == "<<HANDOFF_WRITTEN>>"
    assert set(_LOOP_SENTINELS) == {AWAIT_USER_FLAG, TASK_END_FLAG}


def test_escape_sentinels_breaks_flag():
    # The whole point: a leaked sentinel in tool output must NOT terminate the
    # next turn, so _escape_sentinels rewrites '<<' -> '< <'.
    text = f"tool output containing {AWAIT_USER_FLAG} verbatim"
    escaped = _escape_sentinels(text)
    assert AWAIT_USER_FLAG not in escaped
    assert "< <END_OF_RESPONSE>>" in escaped


def test_continue_prompt_loaded_from_disk():
    assert "END_OF_RESPONSE" in CONTINUE_PROMPT or len(CONTINUE_PROMPT) > 0


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

    assert loop_mod.AWAIT_USER_FLAG is AWAIT_USER_FLAG
    assert loop_mod.TASK_END_FLAG is TASK_END_FLAG
    assert loop_mod.WRITE_HANDOFF_SENTINEL is WRITE_HANDOFF_SENTINEL
    assert loop_mod.CONTINUE_PROMPT is CONTINUE_PROMPT
