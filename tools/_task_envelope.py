"""tools/_task_envelope.py — Shared task-composition envelope for spawned subagents.

Every tool that spawns a subagent via a predefined type needs to append the same two optional/always
sections to the task text it sends: an `## Instructions` section carrying the
parent's free-text `briefing` (only when supplied), and an `## Output` section
carrying `handoff_spec` — what the parent wants in the handoff report — which
is ALWAYS present, falling back to a sensible default when the caller didn't
supply one and no type-specific default is available.

Centralizing this here means the envelope logic (section wording, join
convention, instructions-are-optional/output-is-mandatory ordering) only
needs to be correct once, mirroring the precedent set by
`tools/_handoff_format.py` for handoff-result formatting.
"""
from __future__ import annotations

_SECTION_JOIN = "\n\n---\n\n"

FALLBACK_HANDOFF_SPEC = "Describe what you did, what you found, and any issues encountered."


def wrap_envelope(body: str, briefing: str, handoff_spec: str) -> str:
    """Append the universal `## Instructions` / `## Output` envelope to `body`.

    `## Instructions` is appended only when `briefing` is truthy. `## Output`
    is always appended last, using `handoff_spec` if truthy, else
    `FALLBACK_HANDOFF_SPEC`.
    """
    sections: list[str] = []
    if body:
        sections.append(body)
    if briefing:
        sections.append(f"## Instructions\n{briefing}")
    sections.append(f"## Output\n{handoff_spec or FALLBACK_HANDOFF_SPEC}")
    return _SECTION_JOIN.join(sections)
