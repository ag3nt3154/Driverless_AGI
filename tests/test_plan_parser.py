"""tests/test_plan_parser.py — Unit tests for tools/_plan_parser.py."""
from __future__ import annotations

import pytest

from tools._plan_parser import extract_global_sections, extract_subtask


# ---------------------------------------------------------------------------
# Sample plan fixture
# ---------------------------------------------------------------------------

SAMPLE_PLAN = """\
# Plan — Login Feature

## Context
Why this change is needed: users need to authenticate.

## Approach
High-level strategy: add JWT-based login.

## Files to Modify
- api/auth.py — new login endpoint

## Subtasks

### Subtask 1: Add login endpoint
**Goal:** Implement the POST /login route.
**Requirements:**
- Accept username and password
- Return a signed JWT
**Acceptance Criteria:**
- Returns 200 on valid credentials
#### Tests
test_login.py — tests login flow
test_auth.py — tests token validation

### Subtask 2: Add logout endpoint
**Goal:** Implement the POST /logout route.
**Requirements:**
- Invalidate the JWT
**Acceptance Criteria:**
- Returns 204 on success
#### Tests
test_logout.py — tests logout flow

### Subtask 3: No tests subtask
**Goal:** Subtask without a Tests section.
**Requirements:**
- Just some requirements

## Notes
Salient findings: JWT lib is already installed.

## Verification
Run the test suite with pytest.
"""

# A minimal plan with only some sections
SPARSE_PLAN = """\
# Plan — Sparse

## Context
Only context here.

## Subtasks

### Subtask 1: The only task
**Goal:** Do the thing.
"""

# Plan with no global sections at all
EMPTY_PLAN = """\
# Plan — Empty

## Subtasks

### Subtask 1: Task A
**Goal:** Something.
"""


# ---------------------------------------------------------------------------
# extract_global_sections
# ---------------------------------------------------------------------------

class TestExtractGlobalSections:
    def test_returns_context_section(self):
        result = extract_global_sections(SAMPLE_PLAN)
        assert "## Context" in result
        assert "users need to authenticate" in result

    def test_returns_approach_section(self):
        result = extract_global_sections(SAMPLE_PLAN)
        assert "## Approach" in result
        assert "JWT-based login" in result

    def test_returns_notes_section(self):
        result = extract_global_sections(SAMPLE_PLAN)
        assert "## Notes" in result
        assert "JWT lib is already installed" in result

    def test_excludes_files_to_modify(self):
        result = extract_global_sections(SAMPLE_PLAN)
        assert "## Files to Modify" not in result
        assert "api/auth.py" not in result

    def test_excludes_subtasks_section(self):
        result = extract_global_sections(SAMPLE_PLAN)
        assert "## Subtasks" not in result

    def test_excludes_verification_section(self):
        result = extract_global_sections(SAMPLE_PLAN)
        assert "## Verification" not in result
        assert "Run the test suite" not in result

    def test_sections_separated_by_blank_line(self):
        result = extract_global_sections(SAMPLE_PLAN)
        # There should be double newlines between sections
        assert "\n\n" in result

    def test_sparse_plan_missing_approach_and_notes(self):
        result = extract_global_sections(SPARSE_PLAN)
        assert "## Context" in result
        assert "## Approach" not in result
        assert "## Notes" not in result

    def test_no_global_sections_returns_empty_string(self):
        result = extract_global_sections(EMPTY_PLAN)
        assert result == ""

    def test_empty_input_returns_empty_string(self):
        assert extract_global_sections("") == ""

    def test_preserves_section_body_content(self):
        result = extract_global_sections(SAMPLE_PLAN)
        # Body text should be present, not truncated
        assert "users need to authenticate" in result
        assert "JWT-based login" in result
        assert "JWT lib is already installed" in result


# ---------------------------------------------------------------------------
# extract_subtask — found cases
# ---------------------------------------------------------------------------

class TestExtractSubtaskFound:
    def test_extracts_subtask_1_by_exact_name(self):
        result = extract_subtask(SAMPLE_PLAN, "Add login endpoint")
        assert "### Subtask 1: Add login endpoint" in result

    def test_extracts_subtask_2_by_exact_name(self):
        result = extract_subtask(SAMPLE_PLAN, "Add logout endpoint")
        assert "### Subtask 2: Add logout endpoint" in result

    def test_subtask_body_contains_goal(self):
        result = extract_subtask(SAMPLE_PLAN, "Add login endpoint")
        assert "Implement the POST /login route" in result

    def test_subtask_body_contains_requirements(self):
        result = extract_subtask(SAMPLE_PLAN, "Add login endpoint")
        assert "Accept username and password" in result
        assert "Return a signed JWT" in result

    def test_subtask_body_contains_acceptance_criteria(self):
        result = extract_subtask(SAMPLE_PLAN, "Add login endpoint")
        assert "Returns 200 on valid credentials" in result

    def test_subtask_body_contains_tests_by_default(self):
        result = extract_subtask(SAMPLE_PLAN, "Add login endpoint")
        assert "#### Tests" in result
        assert "test_login.py" in result

    def test_subtask_body_does_not_bleed_into_next_subtask(self):
        result = extract_subtask(SAMPLE_PLAN, "Add login endpoint")
        assert "### Subtask 2" not in result
        assert "logout" not in result

    def test_case_insensitive_name_match(self):
        result = extract_subtask(SAMPLE_PLAN, "add login endpoint")
        assert "### Subtask 1: Add login endpoint" in result

    def test_partial_name_match(self):
        result = extract_subtask(SAMPLE_PLAN, "login")
        assert "### Subtask 1: Add login endpoint" in result

    def test_last_subtask_does_not_include_notes_section(self):
        # Subtask 3 is the last ### before ## Notes
        result = extract_subtask(SAMPLE_PLAN, "No tests subtask")
        assert "## Notes" not in result
        assert "JWT lib is already installed" not in result


# ---------------------------------------------------------------------------
# extract_subtask — include_tests=False
# ---------------------------------------------------------------------------

class TestExtractSubtaskWithoutTests:
    def test_tests_section_stripped(self):
        result = extract_subtask(SAMPLE_PLAN, "Add login endpoint", include_tests=False)
        assert "#### Tests" not in result

    def test_test_file_references_stripped(self):
        result = extract_subtask(SAMPLE_PLAN, "Add login endpoint", include_tests=False)
        assert "test_login.py" not in result
        assert "test_auth.py" not in result

    def test_heading_and_requirements_still_present(self):
        result = extract_subtask(SAMPLE_PLAN, "Add login endpoint", include_tests=False)
        assert "### Subtask 1: Add login endpoint" in result
        assert "Accept username and password" in result

    def test_acceptance_criteria_still_present(self):
        result = extract_subtask(SAMPLE_PLAN, "Add login endpoint", include_tests=False)
        assert "Returns 200 on valid credentials" in result

    def test_subtask_without_tests_section_unaffected(self):
        result_with = extract_subtask(SAMPLE_PLAN, "No tests subtask", include_tests=True)
        result_without = extract_subtask(SAMPLE_PLAN, "No tests subtask", include_tests=False)
        assert result_with == result_without

    def test_subtask_2_tests_stripped(self):
        result = extract_subtask(SAMPLE_PLAN, "Add logout endpoint", include_tests=False)
        assert "#### Tests" not in result
        assert "test_logout.py" not in result
        assert "Returns 204 on success" in result

    def test_include_tests_true_default(self):
        # Default behaviour (include_tests omitted) should include Tests
        result_default = extract_subtask(SAMPLE_PLAN, "Add login endpoint")
        result_explicit = extract_subtask(SAMPLE_PLAN, "Add login endpoint", include_tests=True)
        assert result_default == result_explicit


# ---------------------------------------------------------------------------
# extract_subtask — not found cases
# ---------------------------------------------------------------------------

class TestExtractSubtaskNotFound:
    def test_returns_empty_string_for_unknown_name(self):
        result = extract_subtask(SAMPLE_PLAN, "Nonexistent task")
        assert result == ""

    def test_returns_empty_string_for_empty_plan(self):
        result = extract_subtask("", "Add login endpoint")
        assert result == ""

    def test_returns_empty_string_not_none(self):
        result = extract_subtask(SAMPLE_PLAN, "totally missing")
        assert result is not None
        assert isinstance(result, str)

    def test_returns_empty_string_for_empty_name(self):
        # An empty string matches every subtask heading; implementation may
        # return the first subtask. Either way it must not raise.
        result = extract_subtask(SAMPLE_PLAN, "xyzzy-no-match-123456")
        assert result == ""

    def test_no_subtasks_in_plan(self):
        plan = "# Plan\n\n## Context\nSome context.\n"
        result = extract_subtask(plan, "anything")
        assert result == ""

    def test_include_tests_false_on_missing_subtask_returns_empty(self):
        result = extract_subtask(SAMPLE_PLAN, "does not exist", include_tests=False)
        assert result == ""


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_subtask_at_end_of_file_no_trailing_newline(self):
        plan = "## Subtasks\n\n### Subtask 1: Final task\n**Goal:** Last one."
        result = extract_subtask(plan, "Final task")
        assert "### Subtask 1: Final task" in result
        assert "Last one" in result

    def test_global_sections_order_preserved(self):
        result = extract_global_sections(SAMPLE_PLAN)
        ctx_pos = result.find("## Context")
        approach_pos = result.find("## Approach")
        notes_pos = result.find("## Notes")
        assert ctx_pos < approach_pos < notes_pos

    def test_subtask_body_ends_before_next_h2(self):
        # Subtask 3 should end before ## Notes
        result = extract_subtask(SAMPLE_PLAN, "No tests subtask")
        assert "## Notes" not in result

    def test_multiple_tests_sections_only_strips_tests(self):
        plan = (
            "## Subtasks\n\n"
            "### Subtask 1: Task with lots\n"
            "**Goal:** Do it.\n"
            "#### Tests\n"
            "test_a.py\n"
            "#### Other\n"
            "some other section\n"
        )
        result = extract_subtask(plan, "Task with lots", include_tests=False)
        assert "#### Tests" not in result
        assert "test_a.py" not in result
        # The #### Other section that follows Tests should be retained
        assert "#### Other" in result
        assert "some other section" in result


# ---------------------------------------------------------------------------
# Task keyword support (alongside Subtask)
# ---------------------------------------------------------------------------

TASK_KEYWORD_PLAN = """\
# Plan: Feature

## Subtasks

### Task 1: [x] Setup project
**Goal:** Init the repo.

### Task 2: [~] Implement core
**Goal:** Build the thing.

### Task 3: [ ] Add tests
**Goal:** Test the thing.
"""

MIXED_KEYWORD_PLAN = """\
# Plan: Migration

## Subtasks

### Subtask 1: [x] Old format task
**Goal:** Legacy.

### Task 2: [ ] New format task
**Goal:** Modern.
"""


class TestTaskKeywordSupport:
    def test_parse_statuses_with_task_keyword(self):
        from tools._plan_parser import parse_subtask_statuses
        statuses = parse_subtask_statuses(TASK_KEYWORD_PLAN)
        assert len(statuses) == 3
        assert statuses[0] == {"name": "Setup project", "status": "complete"}
        assert statuses[1] == {"name": "Implement core", "status": "in_progress"}
        assert statuses[2] == {"name": "Add tests", "status": "pending"}

    def test_parse_statuses_mixed_keywords(self):
        from tools._plan_parser import parse_subtask_statuses
        statuses = parse_subtask_statuses(MIXED_KEYWORD_PLAN)
        assert len(statuses) == 2
        assert statuses[0]["name"] == "Old format task"
        assert statuses[1]["name"] == "New format task"

    def test_extract_subtask_with_task_keyword(self):
        result = extract_subtask(TASK_KEYWORD_PLAN, "Implement core")
        assert "### Task 2:" in result
        assert "Build the thing" in result

    def test_extract_subtask_with_task_keyword_no_bleed(self):
        result = extract_subtask(TASK_KEYWORD_PLAN, "Implement core")
        assert "### Task 3:" not in result


from pathlib import Path


class TestUpdateTaskMarker:
    def test_marks_pending_to_in_progress(self, tmp_path):
        from tools._plan_parser import update_task_marker
        plan = tmp_path / "plan.md"
        plan.write_text(TASK_KEYWORD_PLAN, encoding="utf-8")

        statuses = update_task_marker(plan, task_number=3, new_status="in_progress")

        text = plan.read_text(encoding="utf-8")
        assert "### Task 3: [~] Add tests" in text
        assert statuses[2]["status"] == "in_progress"

    def test_marks_in_progress_to_complete(self, tmp_path):
        from tools._plan_parser import update_task_marker
        plan = tmp_path / "plan.md"
        plan.write_text(TASK_KEYWORD_PLAN, encoding="utf-8")

        statuses = update_task_marker(plan, task_number=2, new_status="complete")

        text = plan.read_text(encoding="utf-8")
        assert "### Task 2: [x] Implement core" in text
        assert statuses[1]["status"] == "complete"

    def test_marks_task_as_failed(self, tmp_path):
        from tools._plan_parser import update_task_marker
        plan = tmp_path / "plan.md"
        plan.write_text(TASK_KEYWORD_PLAN, encoding="utf-8")

        statuses = update_task_marker(plan, task_number=1, new_status="failed")

        text = plan.read_text(encoding="utf-8")
        assert "### Task 1: [!] Setup project" in text

    def test_works_with_subtask_keyword(self, tmp_path):
        from tools._plan_parser import update_task_marker
        plan = tmp_path / "plan.md"
        plan.write_text(MIXED_KEYWORD_PLAN, encoding="utf-8")

        statuses = update_task_marker(plan, task_number=1, new_status="in_progress")

        text = plan.read_text(encoding="utf-8")
        assert "### Subtask 1: [~] Old format task" in text

    def test_invalid_task_number_raises(self, tmp_path):
        from tools._plan_parser import update_task_marker
        plan = tmp_path / "plan.md"
        plan.write_text(TASK_KEYWORD_PLAN, encoding="utf-8")

        with pytest.raises(ValueError, match="Task 99 not found"):
            update_task_marker(plan, task_number=99, new_status="complete")

    def test_adds_marker_to_heading_without_one(self, tmp_path):
        from tools._plan_parser import update_task_marker
        plan_text = (
            "# Plan\n\n## Subtasks\n\n"
            "### Task 1: No marker task\n**Goal:** Do it.\n"
        )
        plan = tmp_path / "plan.md"
        plan.write_text(plan_text, encoding="utf-8")

        statuses = update_task_marker(
            plan, task_number=1, new_status="in_progress",
        )

        text = plan.read_text(encoding="utf-8")
        assert "### Task 1: [~] No marker task" in text
        assert statuses[0]["status"] == "in_progress"

    def test_returns_all_statuses_after_update(self, tmp_path):
        from tools._plan_parser import update_task_marker
        plan = tmp_path / "plan.md"
        plan.write_text(TASK_KEYWORD_PLAN, encoding="utf-8")

        statuses = update_task_marker(plan, task_number=2, new_status="complete")

        assert len(statuses) == 3
        assert statuses[0]["status"] == "complete"   # was already [x]
        assert statuses[1]["status"] == "complete"   # just updated
        assert statuses[2]["status"] == "pending"    # unchanged
