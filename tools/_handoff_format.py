"""tools/_handoff_format.py — Shared formatting for subagent handoff results.

Every tool that spawns or resumes a subagent (spawn_subagent, cli_subagent,
extend_timeout, explore_files, web_research) branches on the same "ok" /
"ok_unverified" statuses from `run_subagent`/`resume_subagent` and needs to
render identical output: inline the handoff file's content so the caller
always sees it without a separate `read` call, and prepend an unmistakable
warning banner when the subagent never called `write_handoff` (i.e. its
last message was scraped into the handoff file instead of a deliberate
structured report).

Centralizing this here means the banner wording/emoji and the graceful
degrade-on-unreadable-file behaviour only need to be correct once.
"""
from __future__ import annotations

from pathlib import Path

_UNVERIFIED_BANNER = (
    "⚠️ UNVERIFIED HANDOFF — the subagent exited without calling "
    "`write_handoff`. The\ncontent below was scraped from its last message "
    "and may be incomplete or informal.\n\n"
)


def format_handoff_result(handoff_path: str, unverified: bool = False) -> str:
    """Format a subagent's "ok"/"ok_unverified" result, inlining handoff content.

    Reads `handoff_path` and returns a message combining a completion notice
    with the file's content. When `unverified` is True, prepends a warning
    banner. If the file can't be read (missing, permissions, bad encoding),
    degrades gracefully to an error message instead of raising.
    """
    banner = _UNVERIFIED_BANNER if unverified else ""
    try:
        content = Path(handoff_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return (
            f"{banner}Subagent completed. Handoff written to: {handoff_path}\n\n"
            f"(could not read handoff file: {exc})"
        )
    return (
        f"{banner}Subagent completed. Handoff written to: {handoff_path}\n\n"
        f"--- Handoff content ---\n{content}"
    )
