"""Tests for the strict structured report returned by the ``/wtf`` subagent."""
from __future__ import annotations

import pytest

from agent.wtf_report import parse_wtf_report


def test_parse_wtf_report_extracts_the_three_required_sections():
    """The parent needs named fields instead of an unstructured handoff blob."""
    report = parse_wtf_report(
        "## Description\n"
        "The application fails when opening a missing file.\n\n"
        "## Error Report\n"
        "`FileNotFoundError` escapes from the command handler.\n\n"
        "## Suggested Fix\n"
        "Translate the exception into the existing user-facing error result.\n"
    )

    assert report.description == "The application fails when opening a missing file."
    assert report.error_report == "`FileNotFoundError` escapes from the command handler."
    assert report.suggested_fix == (
        "Translate the exception into the existing user-facing error result."
    )


def test_parse_wtf_report_accepts_crlf_headings():
    """Windows-written handoffs must retain the same strict report contract."""
    report = parse_wtf_report(
        "## Description\r\nObserved behavior.\r\n\r\n"
        "## Error Report\r\nRelevant exception.\r\n\r\n"
        "## Suggested Fix\r\nA focused repair."
    )

    assert report.description == "Observed behavior."
    assert report.error_report == "Relevant exception."
    assert report.suggested_fix == "A focused repair."


@pytest.mark.parametrize("section", ["Description", "Error Report", "Suggested Fix"])
def test_parse_wtf_report_rejects_a_missing_required_section(section):
    """A parent must never append a report that lacks one of its decision fields."""
    sections = {
        "Description": "Observed behavior.",
        "Error Report": "Relevant exception.",
        "Suggested Fix": "A focused repair.",
    }
    del sections[section]
    text = "\n\n".join(f"## {name}\n{body}" for name, body in sections.items())

    with pytest.raises(ValueError, match=f"Missing required section: {section}"):
        parse_wtf_report(text)


@pytest.mark.parametrize("section", ["Description", "Error Report", "Suggested Fix"])
def test_parse_wtf_report_rejects_an_empty_required_section(section):
    """An empty heading would otherwise look valid while withholding the diagnosis."""
    sections = {
        "Description": "Observed behavior.",
        "Error Report": "Relevant exception.",
        "Suggested Fix": "A focused repair.",
    }
    sections[section] = "\n\n"
    text = "\n\n".join(f"## {name}\n{body}" for name, body in sections.items())

    with pytest.raises(ValueError, match=f"Empty section: {section}"):
        parse_wtf_report(text)


def test_parse_wtf_report_rejects_unknown_level_two_headings():
    """Unexpected headings make the report contract ambiguous for the parent."""
    text = (
        "## Description\nObserved behavior.\n\n"
        "## Error Report\nRelevant exception.\n\n"
        "## Notes\nUncontracted content.\n\n"
        "## Suggested Fix\nA focused repair."
    )

    with pytest.raises(ValueError, match="Unknown section: Notes"):
        parse_wtf_report(text)


@pytest.mark.parametrize("level", ["#", "###"])
def test_parse_wtf_report_rejects_required_headings_at_the_wrong_level(level):
    """Only level-two headings delimit structured fields reliably."""
    text = (
        f"{level} Description\nObserved behavior.\n\n"
        "## Error Report\nRelevant exception.\n\n"
        "## Suggested Fix\nA focused repair."
    )

    with pytest.raises(ValueError, match="Expected level-2 heading for section: Description"):
        parse_wtf_report(text)


def test_parse_wtf_report_rejects_duplicate_headings():
    """Duplicated fields could otherwise let later content silently win."""
    text = (
        "## Description\nObserved behavior.\n\n"
        "## Error Report\nRelevant exception.\n\n"
        "## Description\nConflicting behavior.\n\n"
        "## Suggested Fix\nA focused repair."
    )

    with pytest.raises(ValueError, match="Duplicate section: Description"):
        parse_wtf_report(text)


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "diagnostic preamble\n\n"
            "## Description\nObserved behavior.\n\n"
            "## Error Report\nRelevant exception.\n\n"
            "## Suggested Fix\nA focused repair.",
            "Unexpected preamble before first section",
        ),
        (
            "## Error Report\nRelevant exception.\n\n"
            "## Description\nObserved behavior.\n\n"
            "## Suggested Fix\nA focused repair.",
            "Sections out of order",
        ),
    ],
)
def test_parse_wtf_report_rejects_preamble_and_wrong_section_order(text, expected):
    """The parent accepts only the exact report sequence promised by the preset."""
    with pytest.raises(ValueError, match=expected):
        parse_wtf_report(text)


def test_parse_wtf_report_preserves_internal_body_text_and_trims_blank_edges():
    """The parent must retain diagnostics exactly enough for a useful follow-up."""
    report = parse_wtf_report(
        "## Description\n\n  First line.\n\n  Second line.  \n\n"
        "## Error Report\n\n  Exception detail.  \n\n"
        "## Suggested Fix\n\n  Keep the internal formatting.  \n"
    )

    assert report.description == "First line.\n\n  Second line."
    assert report.error_report == "Exception detail."
    assert report.suggested_fix == "Keep the internal formatting."
