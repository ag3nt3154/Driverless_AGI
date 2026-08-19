"""Structured report parsing for the read-only ``/wtf`` diagnostic subagent."""
from __future__ import annotations

from dataclasses import dataclass
import re


_SECTION_NAMES = ("Description", "Error Report", "Suggested Fix")
_HEADING_RE = re.compile(
    r"^(?P<marks>#{1,6})[ \t]+(?P<title>[^\r\n]*?)[ \t]*\r?$", re.MULTILINE
)


@dataclass(frozen=True, slots=True)
class WtfReport:
    """The three diagnostic fields a parent can safely reference."""

    description: str
    error_report: str
    suggested_fix: str


def parse_wtf_report(text: str) -> WtfReport:
    """Parse the exact level-two heading contract emitted by the ``/wtf`` preset."""
    headings = list(_HEADING_RE.finditer(text))
    if headings and text[:headings[0].start()].strip():
        raise ValueError("Unexpected preamble before first section")
    _validate_headings(headings)
    values = _extract_sections(text, headings)

    for section in _SECTION_NAMES:
        if section not in values:
            raise ValueError(f"Missing required section: {section}")
        if not values[section]:
            raise ValueError(f"Empty section: {section}")
    actual_order = tuple(heading["title"] for heading in headings)
    if actual_order != _SECTION_NAMES:
        raise ValueError(
            f"Sections out of order: expected {', '.join(_SECTION_NAMES)}"
        )

    return WtfReport(
        description=values["Description"],
        error_report=values["Error Report"],
        suggested_fix=values["Suggested Fix"],
    )


def _validate_headings(headings: list[re.Match[str]]) -> None:
    """Reject duplicate, unknown, and non-level-two headings before extraction."""
    seen: set[str] = set()
    for heading in headings:
        title = heading["title"]
        if heading["marks"] != "##":
            if title in _SECTION_NAMES:
                raise ValueError(f"Expected level-2 heading for section: {title}")
            raise ValueError(f"Unknown heading: {title}")
        if title not in _SECTION_NAMES:
            raise ValueError(f"Unknown section: {title}")
        if title in seen:
            raise ValueError(f"Duplicate section: {title}")
        seen.add(title)


def _extract_sections(text: str, headings: list[re.Match[str]]) -> dict[str, str]:
    """Return heading bodies with only surrounding whitespace removed."""
    values: dict[str, str] = {}
    for index, heading in enumerate(headings):
        if heading["marks"] != "##" or heading["title"] not in _SECTION_NAMES:
            continue
        body_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        values[heading["title"]] = text[heading.end():body_end].strip()
    return values
