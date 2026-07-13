"""tests/test_show_plan.py — ShowPlanTool.on_plan_shown wiring."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools.show_plan import ShowPlanTool


@pytest.fixture
def plan_file(tmp_path: Path) -> Path:
    f = tmp_path / "plan.md"
    f.write_text("# Plan: Do the thing\n", encoding="utf-8")
    return f


class TestOnPlanShownWiring:
    def test_interactive_mode_fires_on_plan_shown(self, plan_file: Path):
        callbacks = MagicMock()
        callbacks.on_ask_user.return_value = "ok"
        tool = ShowPlanTool(plan_file=plan_file, callbacks=callbacks, interactive=True)

        tool.run()

        callbacks.on_plan_shown.assert_called_once_with()

    def test_autonomous_mode_does_not_fire_on_plan_shown(self, plan_file: Path):
        callbacks = MagicMock()
        tool = ShowPlanTool(plan_file=plan_file, callbacks=callbacks, interactive=False)

        tool.run()

        callbacks.on_plan_shown.assert_not_called()

    def test_no_callbacks_does_not_raise(self, plan_file: Path):
        tool = ShowPlanTool(plan_file=plan_file, callbacks=None, interactive=True)

        result = tool.run()

        assert "approved by the user" in result
