"""tests/test_revise_history_tui.py — TUI revise-history modal and command."""
from __future__ import annotations

import pytest

from agent.session_log import StepInfo


class TestReviseConfirmScreen:
    def test_formats_single_step_summary(self):
        from tui.revise_history import format_step_summaries
        infos = [
            StepInfo(step_number=3, turn=2, tool_names=["read_file", "edit_file"],
                     assistant_snippet="I've updated the config to use the new...",
                     event_range=(10, 15)),
        ]
        text = format_step_summaries(infos)
        assert "Step 3" in text
        assert "turn 2" in text
        assert "read_file" in text
        assert "edit_file" in text
        assert "I've updated the config" in text

    def test_formats_multiple_step_summaries(self):
        from tui.revise_history import format_step_summaries
        infos = [
            StepInfo(step_number=3, turn=2, tool_names=["edit_file"],
                     assistant_snippet="Edited config...", event_range=(10, 15)),
            StepInfo(step_number=2, turn=2, tool_names=["grep"],
                     assistant_snippet="Found 3 matches...", event_range=(5, 9)),
        ]
        text = format_step_summaries(infos)
        assert "Step 3" in text
        assert "Step 2" in text

    def test_formats_step_with_no_tools(self):
        from tui.revise_history import format_step_summaries
        infos = [
            StepInfo(step_number=1, turn=1, tool_names=[],
                     assistant_snippet="Hello!", event_range=(1, 3)),
        ]
        text = format_step_summaries(infos)
        assert "Step 1" in text
        assert "Hello!" in text
