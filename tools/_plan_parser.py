"""tools/_plan_parser.py — Utility for parsing plan markdown files.

Plan file format:
    # Plan — <title>

    ## Context
    ...

    ## Approach
    ...

    ## Files to Modify
    ...

    ## Subtasks

    ### Subtask 1: <name>
    ...
    #### Tests
    ...

    ### Subtask 2: <name>
    ...

    ## Notes
    ...

    ## Verification
    ...
"""
from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_into_sections(plan_text: str) -> list[tuple[str, str]]:
    """Return a list of (heading_line, body_text) pairs for every ## section.

    The heading_line includes the leading ``##`` marker.  body_text is
    everything from the line after the heading up to (but not including) the
    next ``##`` heading or EOF.
    """
    sections: list[tuple[str, str]] = []
    # Match ## headings (not ### or deeper)
    pattern = re.compile(r'^(##\s+.+)$', re.MULTILINE)
    matches = list(pattern.finditer(plan_text))

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(plan_text)
        body = plan_text[start:end].strip()
        sections.append((heading, body))

    return sections


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_GLOBAL_SECTION_NAMES = {"context", "approach", "notes"}


def extract_global_sections(plan_text: str) -> str:
    """Return the concatenated text of the ## Context, ## Approach, and ## Notes sections.

    Sections are separated by a blank line.  Returns an empty string if none
    of the three sections are present.
    """
    parts: list[str] = []
    for heading, body in _split_into_sections(plan_text):
        # Strip '## ' prefix and normalise to lowercase for matching
        section_name = re.sub(r'^##\s+', '', heading).strip().lower()
        if section_name in _GLOBAL_SECTION_NAMES:
            parts.append(f"{heading}\n{body}" if body else heading)

    return "\n\n".join(parts)


def extract_subtask(plan_text: str, subtask_name: str, include_tests: bool = True) -> str:
    """Return the ``### Subtask N: <name>`` block that contains *subtask_name*.

    Matching is case-insensitive substring: the function checks whether
    *subtask_name* appears anywhere in the ``###`` heading line.

    When *include_tests* is ``False``, the ``#### Tests`` subsection (and
    everything under it up to the next ``####``, ``###``, ``##`` heading or
    EOF) is stripped before returning.

    Returns an empty string if no matching subtask is found.
    """
    # Split on ### headings; ## headings also terminate a subtask block
    # Strategy: find all ### or ## heading positions and extract the block.
    heading_pattern = re.compile(r'^(#{2,3}\s+.+)$', re.MULTILINE)
    matches = list(heading_pattern.finditer(plan_text))

    target_idx: int | None = None
    for i, match in enumerate(matches):
        line = match.group(1)
        # Only consider ### headings that contain subtask_name (case-insensitive)
        if line.startswith('###') and subtask_name.lower() in line.lower():
            target_idx = i
            break

    if target_idx is None:
        return ""

    # Determine the body extent: ends at the next ### or ## heading, or EOF
    start = matches[target_idx].start()
    end = len(plan_text)
    for j in range(target_idx + 1, len(matches)):
        next_line = matches[j].group(1)
        # Any ## or ### heading ends this subtask
        if next_line.startswith('##'):
            end = matches[j].start()
            break

    block = plan_text[start:end].rstrip()

    if not include_tests:
        block = _strip_tests_subsection(block)

    return block


def parse_subtask_statuses(plan_text: str) -> list[dict]:
    """Return a list of subtask status dicts parsed from ``### Subtask N: [marker] name`` headings.

    Each dict has keys:
        ``name``   — the subtask name string (everything after the marker, stripped)
        ``status`` — one of ``"pending"``, ``"in_progress"``, ``"complete"``,
                     ``"failed"``, or ``"unknown"``

    Headings without a status marker (e.g. ``### Subtask 1: name``) are returned
    with ``status="unknown"`` rather than being silently dropped.
    Returns an empty list for empty or malformed input.
    """
    if not plan_text:
        return []

    _MARKER_MAP = {" ": "pending", "~": "in_progress", "x": "complete", "!": "failed"}
    _WITH_MARKER = re.compile(
        r'^###\s+(?:Subtask|Task)\s+\d+:\s*\[([ ~x!])\]\s*(.+)$',
        re.MULTILINE,
    )
    _WITHOUT_MARKER = re.compile(
        r'^###\s+(?:Subtask|Task)\s+\d+:(?!\s*\[[ ~x!]\])\s*(.+)$',
        re.MULTILINE,
    )

    results: list[dict] = []

    for m in _WITH_MARKER.finditer(plan_text):
        marker, name = m.group(1), m.group(2).strip()
        results.append({"name": name, "status": _MARKER_MAP.get(marker, "unknown"),
                         "_pos": m.start()})

    for m in _WITHOUT_MARKER.finditer(plan_text):
        name = m.group(1).strip()
        if name:
            results.append({"name": name, "status": "unknown", "_pos": m.start()})

    results.sort(key=lambda d: d.pop("_pos"))
    return results


def update_task_marker(
    plan_path: Path, task_number: int, new_status: str,
) -> list[dict]:
    """Update the status marker for the Nth task heading in a plan file.

    Writes the change to disk and returns the full status list after
    the update (same format as ``parse_subtask_statuses``).

    Raises ``ValueError`` if *task_number* does not match any heading.
    """
    _STATUS_TO_MARKER = {
        "pending": " ", "in_progress": "~",
        "complete": "x", "failed": "!",
    }
    marker = _STATUS_TO_MARKER.get(new_status)
    if marker is None:
        raise ValueError(
            f"Invalid status {new_status!r}; "
            f"expected one of {list(_STATUS_TO_MARKER)}"
        )

    text = plan_path.read_text(encoding="utf-8")

    # Match both flavours: ### Task N: ... and ### Subtask N: ...
    # With or without an existing [marker].
    _HEADING = re.compile(
        r'^(###\s+(?:Subtask|Task)\s+\d+:\s*)'
        r'(?:\[[ ~x!]\]\s*)?'
        r'(.+)$',
        re.MULTILINE,
    )
    matches = list(_HEADING.finditer(text))
    if task_number < 1 or task_number > len(matches):
        raise ValueError(
            f"Task {task_number} not found "
            f"(plan has {len(matches)} task headings)"
        )

    m = matches[task_number - 1]
    prefix, name = m.group(1), m.group(2)
    replacement = f"{prefix}[{marker}] {name}"
    text = text[:m.start()] + replacement + text[m.end():]

    plan_path.write_text(text, encoding="utf-8")
    return parse_subtask_statuses(text)


def _strip_tests_subsection(block: str) -> str:
    """Remove the ``#### Tests`` subsection from a subtask block.

    Everything from the ``#### Tests`` heading up to (but not including) the
    next ``####``, ``###``, or ``##`` heading — or the end of the block — is
    removed.
    """
    # Find #### Tests heading
    tests_pattern = re.compile(r'^####\s+Tests\s*$', re.MULTILINE | re.IGNORECASE)
    m = tests_pattern.search(block)
    if not m:
        return block

    tests_start = m.start()

    # Find the end of the Tests subsection: next ####/###/## heading or EOF
    next_heading = re.compile(r'^#{2,4}\s+', re.MULTILINE)
    after = next_heading.search(block, m.end())
    if after:
        tests_end = after.start()
    else:
        tests_end = len(block)

    # Stitch together the block without the Tests portion, trimming trailing whitespace
    stripped = block[:tests_start].rstrip() + block[tests_end:]
    return stripped.rstrip()
