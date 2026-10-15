"""Contract checks: plans written from the write-plan skill's inline format feed delivery.

The skill documents the plan format as fenced examples in its SKILL.md (the header,
the subtask structure and the runtime sections). These tests assemble a plan from
exactly those examples, so changing the writer format incompatibly fails here.
"""

from pathlib import Path
import re
import runpy

from tools._plan_parser import (
    extract_global_sections,
    extract_subtask,
    parse_subtask_statuses,
    update_task_marker,
)


ROOT = Path(__file__).parents[1]
SKILL = ROOT / ".dagi" / "skills" / "write-plan" / "SKILL.md"


def _skill_examples() -> dict[str, str]:
    """Return the skill's fenced markdown examples keyed by the ``##`` section they sit in."""
    examples: dict[str, str] = {}
    section = None
    fence = None  # the opening backticks while inside a fenced block
    body: list[str] = []
    for line in SKILL.read_text(encoding="utf-8").splitlines():
        if fence is None:
            opening = re.match(r"^(`{3,})markdown\s*$", line)
            if opening:
                fence, body = opening.group(1), []
            elif line.startswith("## "):
                section = line[3:].strip()
        elif line.strip() == fence:
            examples.setdefault(section, "\n".join(body) + "\n")
            fence = None
        else:
            body.append(line)
    return examples


def _subtask(number: int, name: str, requirement: str, test_file: str) -> str:
    block = _skill_examples()["Subtask Structure"]
    block = block.replace("### Subtask N: [ ] <Component Name>",
                          f"### Subtask {number}: [ ] {name}")
    block = block.replace("- Bulleted list of what must be true.", f"- {requirement}")
    return block.replace("Test file paths and one-line description of what each verifies.",
                         f"{test_file} — verifies {name.lower()}.")


def _render_plan() -> str:
    """Assemble a two-subtask plan from the skill's own examples."""
    examples = _skill_examples()
    header = examples["Plan Document Header"]
    header = header.replace("[Feature Name]", "Widget Import")
    header = header.replace("[One sentence describing what this builds]", "Import widgets safely.")
    header = re.sub(r"\[The spec's project-wide requirements.*?\]", "Python 3.11 or newer.",
                    header, flags=re.DOTALL)
    return "\n".join([
        header.rstrip().removesuffix("---").rstrip(),
        "",
        "## Subtasks",
        "",
        _subtask(1, "Validate widgets", "Reject malformed widget records.",
                 "tests/test_widgets.py"),
        _subtask(2, "Validate", "Validate the import manifest.", "tests/test_manifest.py"),
        examples["Plan template (runtime sections)"],
    ])


def test_skill_documents_every_format_example():
    assert {"Plan Document Header", "Subtask Structure",
            "Plan template (runtime sections)"} <= set(_skill_examples())


def test_skill_subtask_heading_carries_a_pending_marker():
    """The writer's heading must parse as a known status, never ``unknown``."""
    heading = _skill_examples()["Subtask Structure"].splitlines()[0]
    assert heading == "### Subtask N: [ ] <Component Name>"
    assert parse_subtask_statuses(heading.replace(" N:", " 1:")) == [
        {"name": "<Component Name>", "status": "pending"},
    ]


def test_rendered_plan_feeds_parser_and_worker_payloads():
    plan = _render_plan()

    assert parse_subtask_statuses(plan) == [
        {"name": "Validate widgets", "status": "pending"},
        {"name": "Validate", "status": "pending"},
    ]
    global_context = extract_global_sections(plan)
    assert "Import widgets safely." in global_context
    assert "Python 3.11 or newer." in global_context
    assert "## Notes" in global_context

    first = extract_subtask(plan, "Validate widgets")
    assert "Reject malformed widget records." in first
    assert "tests/test_widgets.py" in first
    assert "#### Tests" in first
    assert "import manifest" not in first

    # The second subtask's name is a prefix of the first's: the exact name must win.
    second = extract_subtask(plan, "Validate")
    assert second.startswith("### Subtask 2: [ ] Validate\n")
    assert "Validate the import manifest." in second
    assert "## Workspace" not in second


def test_marker_round_trip_preserves_subtask_bodies(tmp_path):
    plan_path = tmp_path / "plan.md"
    original = _render_plan()
    plan_path.write_text(original, encoding="utf-8")

    original_second = extract_subtask(original, "2")
    statuses = update_task_marker(plan_path, task_number=2, new_status="in_progress")
    assert [s["status"] for s in statuses] == ["pending", "in_progress"]
    statuses = update_task_marker(plan_path, task_number=1, new_status="complete")
    assert [s["status"] for s in statuses] == ["complete", "in_progress"]
    update_task_marker(plan_path, task_number=2, new_status="failed")
    assert "### Subtask 2: [!] Validate" in plan_path.read_text(encoding="utf-8")

    update_task_marker(plan_path, task_number=1, new_status="pending")
    update_task_marker(plan_path, task_number=2, new_status="pending")
    updated = plan_path.read_text(encoding="utf-8")
    assert extract_subtask(updated, "2") == original_second
    assert updated == original


def test_rendered_plan_composes_real_worker_assignment():
    worker_path = ROOT / ".dagi/subagents/worker/plan_utils.py"
    compose_worker_task = runpy.run_path(str(worker_path))["compose_worker_task"]
    assignment = compose_worker_task(_render_plan(), "Validate")

    assert "Import widgets safely." in assignment
    assert "Python 3.11 or newer." in assignment
    assert "Validate the import manifest." in assignment
    assert "tests/test_manifest.py" in assignment
    assert "tests/test_widgets.py" not in assignment
