"""Contract: improve-yourself's Step 1 intake reads sections TODO.md actually has (review R27)."""

from pathlib import Path
import re

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".dagi" / "workflow" / "improve-yourself" / "workflow.md"
TODO = ROOT / "TODO.md"


def _step_one() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("## Step 1", 1)[1].split("\n## Step 2", 1)[0]


def _in_progress_items(todo: str) -> list[str]:
    section = todo.split("\n## In progress", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^- \*\*(.+?)\*\*", section, re.MULTILINE)


def test_intake_reads_the_in_progress_section_the_todo_has():
    step = _step_one()
    todo = TODO.read_text(encoding="utf-8")
    assert "`## In progress`" in step
    assert "\n## In progress\n" in todo
    assert _in_progress_items(todo), "the intake section has no `- **Title**` items"
    for gone in ("## Work Queue", "review-item", "priority:high"):
        assert gone not in step


def test_intake_defines_choice_identity_and_empty_outcome():
    step = _step_one()
    assert "ask_user" in step  # the user picks the candidate
    assert "Source identity" in step
    assert "No eligible candidate" in step and "stop" in step


def test_empty_in_progress_section_yields_no_items():
    assert _in_progress_items("# TODO\n\n## In progress\n\n## Completed\n- **Done**\n") == []
