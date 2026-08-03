# .dagi/subagents/review/review_utils.py
"""Task body composition for the review subagent."""
from __future__ import annotations


def compose_review_task(
    plan_text: str,
    subtask_name: str,
    worker_handoff_path: str,
    unit_test_paths: list[str],
) -> str:
    """Build the review task body: plan context, subtask being reviewed,
    and worker handoff details.

    Envelope sections (Instructions/Output) are added later by run_subagent.
    """
    from tools._plan_parser import extract_global_sections, extract_subtask

    sections: list[str] = []

    if plan_text:
        global_ctx = extract_global_sections(plan_text)
        if global_ctx:
            sections.append(f"## Plan Context\n{global_ctx}")

        subtask_ctx = extract_subtask(plan_text, subtask_name, include_tests=True)
        if subtask_ctx:
            sections.append(f"## Subtask Being Reviewed\n{subtask_ctx}")

    if worker_handoff_path:
        lines = [
            f"The worker's implementation report is at: {worker_handoff_path}",
            "Read it before evaluating the subtask.",
        ]
        test_list = "\n".join(unit_test_paths) if unit_test_paths else ""
        if test_list:
            lines.append(f"Unit test paths:\n{test_list}")
        sections.append("## Worker Handoff\n" + "\n".join(lines))

    return "\n\n---\n\n".join(sections)
