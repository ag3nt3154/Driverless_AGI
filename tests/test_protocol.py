"""Tests for agent/protocol.py — ToolResult and SideEffect."""
from __future__ import annotations


class TestSideEffect:
    def test_all_expected_members_exist(self):
        from agent.protocol import SideEffect

        expected = {
            "END_TURN",
            "ENTER_PLAN_MODE",
            "EXIT_PLAN_MODE",
            "ALL_TASKS_RESOLVED",
            "RELOAD_SKILLS",
            "SWITCH_MODEL",
        }
        assert set(SideEffect.__members__) == expected

    def test_members_are_distinct(self):
        from agent.protocol import SideEffect

        values = [m.value for m in SideEffect]
        assert len(values) == len(set(values))


class TestToolResult:
    def test_default_side_effect_is_none(self):
        from agent.protocol import ToolResult

        r = ToolResult(output="done")
        assert r.side_effect is None
        assert r.side_effect_data is None

    def test_with_side_effect(self):
        from agent.protocol import SideEffect, ToolResult

        r = ToolResult(output="ok", side_effect=SideEffect.END_TURN)
        assert r.side_effect is SideEffect.END_TURN

    def test_with_side_effect_data(self):
        from agent.protocol import SideEffect, ToolResult

        r = ToolResult(
            output="switching",
            side_effect=SideEffect.SWITCH_MODEL,
            side_effect_data={"tier": "plan"},
        )
        assert r.side_effect_data == {"tier": "plan"}

    def test_output_is_required(self):
        from agent.protocol import ToolResult
        import pytest

        with pytest.raises(TypeError):
            ToolResult()  # type: ignore[call-arg]

    def test_is_plain_result_for_no_side_effect(self):
        from agent.protocol import ToolResult

        r = ToolResult(output="hello")
        assert r.is_plain

    def test_is_not_plain_with_side_effect(self):
        from agent.protocol import SideEffect, ToolResult

        r = ToolResult(output="hello", side_effect=SideEffect.END_TURN)
        assert not r.is_plain


class TestConstants:
    def test_session_context_header(self):
        from agent.protocol import SESSION_CONTEXT_HEADER

        assert SESSION_CONTEXT_HEADER == "## Session Context"

    def test_context_summary_prefix(self):
        from agent.protocol import CONTEXT_SUMMARY_PREFIX

        assert CONTEXT_SUMMARY_PREFIX == "[CONTEXT SUMMARY"

    def test_list_encoding_prefix(self):
        from agent.protocol import LIST_ENCODING_PREFIX

        assert LIST_ENCODING_PREFIX == "__list__:"


class TestBaseToolReturnType:
    def test_base_tool_accepts_tool_result_return(self):
        """BaseTool.run() type hint accepts ToolResult."""
        import inspect
        from agent.base_tool import BaseTool

        sig = inspect.signature(BaseTool.run)
        # Just verify ToolResult is mentioned in the annotation
        annotation = sig.return_annotation
        assert "ToolResult" in str(annotation)


class TestRegistryDispatchToolResult:
    def test_dispatch_passes_through_tool_result(self):
        from agent.base_tool import BaseTool
        from agent.protocol import SideEffect, ToolResult
        from agent.registry import ToolRegistry

        class FakeTool(BaseTool):
            name = "fake"
            description = "fake"
            _parameters = {"type": "object", "properties": {}}

            def run(self) -> ToolResult:
                return ToolResult(output="ok", side_effect=SideEffect.END_TURN)

        reg = ToolRegistry()
        reg.register(FakeTool())
        result = reg.dispatch("fake", {})
        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.END_TURN
