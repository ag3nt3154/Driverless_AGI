"""tests/test_session_surface.py — Ordered surface projection."""
from __future__ import annotations

import pytest

from agent import session_events as ev
from agent.session_log import SessionEvent
from agent.session_surface import Surface, project_event


def _surface_event(seq: int, type: str, data: dict, op=("append")) -> SessionEvent:
    return SessionEvent(seq=seq, time="t", type=type, data=data, surface_op=op)


class TestProjectEvent:
    def test_user_message_preserves_its_role(self):
        """Wiki context and reload notices ride user/message with role='system'.

        The role is durable data, not something the projection decides.
        """
        e = _surface_event(
            1, ev.USER_MESSAGE,
            {"turn": 1, "step": 1, "role": "system", "content": "wiki", "source": "wiki"},
        )
        assert project_event(e) == {"role": "system", "content": "wiki"}

    def test_human_prompt_projects_as_user_role(self):
        e = _surface_event(
            1, ev.USER_MESSAGE,
            {"turn": 1, "step": 1, "role": "user", "content": "do it", "source": "human"},
        )
        assert project_event(e) == {"role": "user", "content": "do it"}

    def test_assistant_message_projects_verbatim(self):
        msg = {"role": "assistant", "content": "hi", "reasoning_content": "thinking"}
        e = _surface_event(1, ev.ASSISTANT_MESSAGE, {"turn": 1, "step": 1, "message": msg})
        assert project_event(e) == msg

    def test_assistant_projection_is_a_copy_not_an_alias(self):
        msg = {"role": "assistant", "content": "hi"}
        e = _surface_event(1, ev.ASSISTANT_MESSAGE, {"turn": 1, "step": 1, "message": msg})
        project_event(e)["content"] = "mutated"
        assert e.data["message"]["content"] == "hi"

    def test_tool_result_projects_to_a_tool_message(self):
        e = _surface_event(
            1, ev.TOOL_RESULT,
            {"turn": 1, "step": 1, "call_id": "c1", "content": "out", "meta": None},
        )
        assert project_event(e) == {"role": "tool", "tool_call_id": "c1", "content": "out"}

    def test_tool_result_preserves_list_content_for_image_results(self):
        blocks = [{"type": "image_url", "image_url": {"url": "data:..."}}]
        e = _surface_event(
            1, ev.TOOL_RESULT,
            {"turn": 1, "step": 1, "call_id": "c1", "content": blocks, "meta": None},
        )
        assert project_event(e)["content"] == blocks

    def test_non_surface_event_is_rejected(self):
        e = SessionEvent(seq=1, time="t", type=ev.TURN_START, data={"turn": 1})
        with pytest.raises(ValueError, match="not a surface event"):
            project_event(e)


class TestSurfaceAppend:
    def test_appends_in_order(self):
        s = Surface()
        s.accept(_surface_event(
            1, ev.USER_MESSAGE,
            {"turn": 1, "step": 1, "role": "user", "content": "a", "source": "human"},
        ))
        s.accept(_surface_event(
            2, ev.ASSISTANT_MESSAGE,
            {"turn": 1, "step": 1, "message": {"role": "assistant", "content": "b"}},
        ))
        assert [m["content"] for m in s.messages()] == ["a", "b"]
        assert s.nodes == (1, 2)

    def test_generation_does_not_move_on_append(self):
        """Appends preserve the reusable KV prefix; only replaces break it."""
        s = Surface()
        before = s.generation
        s.accept(_surface_event(
            1, ev.USER_MESSAGE,
            {"turn": 1, "step": 1, "role": "user", "content": "a", "source": "human"},
        ))
        assert s.generation == before

    def test_messages_returns_a_fresh_list_each_call(self):
        s = Surface()
        s.accept(_surface_event(
            1, ev.USER_MESSAGE,
            {"turn": 1, "step": 1, "role": "user", "content": "a", "source": "human"},
        ))
        first = s.messages()
        first.append({"role": "user", "content": "injected"})
        assert len(s.messages()) == 1

    def test_index_of_locates_a_node(self):
        s = Surface()
        s.accept(_surface_event(
            5, ev.USER_MESSAGE,
            {"turn": 1, "step": 1, "role": "user", "content": "a", "source": "human"},
        ))
        assert s.index_of(5) == 0

    def test_index_of_raises_for_an_absent_node(self):
        with pytest.raises(KeyError):
            Surface().index_of(99)
