"""Behavioral checks for the canonical workflow plan template."""

from pathlib import Path
import runpy

from tools._plan_parser import (
    extract_global_sections,
    extract_subtask,
    parse_subtask_statuses,
    update_task_marker,
)


TEMPLATE = (
    Path(__file__).parents[1]
    / ".dagi"
    / "skills"
    / "write-plan"
    / "references"
    / "plan-template.md"
)


def _render_template() -> str:
    """Fill the documented slots with two concrete subtasks."""
    text = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "[Feature Name]": "Widget Import",
        "[One sentence describing what this builds]": "Import widgets safely.",
        "[2-3 sentences about approach]": "Validate input, then persist widgets.",
        "[Key technologies/libraries]": "Python and SQLite",
        "[path to spec.md in the same artifact directory]": "wiki/tasks/2026-09-26_widget/spec.md",
        "Project-wide requirements from the spec — one line each.": "Python 3.11 or newer.",
        "Uncovered failure modes — one line each with owning task's test.": (
            "Malformed input is rejected."
        ),
        "`<task-branch>`": "`dagi/widget-import`",
        "`<parent-branch>`": "`main`",
        "`<commit-hash>`": "`abc1234`",
        "`wiki/tasks/YYYY-MM-DD_<task>/`": "`wiki/tasks/2026-09-26_widget/`",
        "Pending / In Progress / Verification / Complete / Blocked": "Pending",
        "One sentence.": "Validate each widget before persistence.",
        "- Bulleted list of what must be true.": "- Reject malformed widget records.",
        "- Bulleted list of checkable conditions.": "- Invalid records produce a clear error.",
        "Test file paths and one-line description of what each verifies.": (
            "tests/test_widgets.py — validates rejection."
        ),
        "Unresolved questions or blockers not yet addressed.": "None.",
        (
            "One block per rework cycle:\n- **Subtask N, attempt N:** "
            "blocker summary → resolution (or link to handoff)"
        ): (
            "None."
        ),
        "End-to-end verification commands and expected outcomes.": (
            "Run the focused test suite; all tests pass."
        ),
        "One sentence: what happens next after reading this plan.": (
            "Obtain approval, then deliver."
        ),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("### Subtask 1: [ ] <name>", "### Subtask 1: [ ] Validate widgets")
    second = (
        "### Subtask 2: [ ] Persist widgets\n"
        "**Goal:** Persist validated widgets.\n"
        "**Requirements:**\n- Store the validated record.\n"
        "**Acceptance Criteria:**\n- Stored records can be retrieved.\n"
        "#### Tests\n"
        "tests/test_persistence.py — checks retrieval.\n\n"
    )
    text = text.replace("## Notes", second + "## Notes")
    return text


def test_rendered_template_feeds_parser_and_worker_payloads():
    plan = _render_template()

    statuses = parse_subtask_statuses(plan)
    assert statuses == [
        {"name": "Validate widgets", "status": "pending"},
        {"name": "Persist widgets", "status": "pending"},
    ]

    global_context = extract_global_sections(plan)
    first = extract_subtask(plan, "Validate widgets")
    assert "Python 3.11 or newer." in global_context
    assert "Reject malformed widget records." in first
    assert "Invalid records produce a clear error." in first
    assert "tests/test_widgets.py" in first
    assert "Persist validated widgets" not in first
    assert "tests/test_persistence.py" not in first


def test_marker_round_trip_preserves_subtask_bodies(tmp_path):
    plan_path = tmp_path / "plan.md"
    original = _render_template()
    plan_path.write_text(original, encoding="utf-8")

    original_first = extract_subtask(original, "Validate widgets")
    statuses = update_task_marker(plan_path, task_number=1, new_status="in_progress")
    update_task_marker(plan_path, task_number=1, new_status="complete")
    update_task_marker(plan_path, task_number=1, new_status="pending")
    updated = plan_path.read_text(encoding="utf-8")

    assert statuses[0]["status"] == "in_progress"
    assert "### Subtask 1: [ ] Validate widgets" in updated
    assert extract_subtask(updated, "Validate widgets") == original_first
    assert "Reject malformed widget records." in updated
    assert "tests/test_persistence.py" in updated
    assert "## Notes" in updated
    assert updated == original


def test_rendered_template_composes_real_worker_assignment():
    worker_path = Path(__file__).parents[1] / ".dagi/subagents/worker/plan_utils.py"
    compose_worker_task = runpy.run_path(str(worker_path))["compose_worker_task"]
    assignment = compose_worker_task(_render_template(), "Validate widgets")

    assert "Import widgets safely." in assignment
    assert "Python 3.11 or newer." in assignment
    assert "Reject malformed widget records." in assignment
    assert "Invalid records produce a clear error." in assignment
    assert "tests/test_widgets.py" in assignment
    assert "tests/test_persistence.py" not in assignment
