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
degrade-on-unreadable-file behaviour only need to be correct once. The same
five call sites also duplicated the branch that maps a `run_subagent`/
`resume_subagent` result dict's "status" to a tool's return string —
`dispatch_status_result` centralizes that too.
"""
from __future__ import annotations

import json
from pathlib import Path

_UNVERIFIED_BANNER = (
    "⚠️ UNVERIFIED HANDOFF — the subagent exited without calling "
    "`write_handoff`. The\ncontent below was scraped from its last message "
    "and may be incomplete or informal.\n\n"
)


def unverified_flag_path(handoff_path: Path) -> Path:
    """Return the sidecar '_unverified.flag' path for a given handoff path.

    Written by `tools/subagent_main.py` when a handoff was scraped from the
    subagent's last assistant message (retry+degrade path) rather than
    deliberately reported via `write_handoff`; read by
    `tools/_subagent_runner.py` to decide between "ok" and "ok_unverified".
    Centralized so the writer and reader can't drift on the naming scheme.
    """
    return handoff_path.with_name(f"{handoff_path.stem}_unverified.flag")


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


def dispatch_status_result(
    result: dict,
    error_prefix: str,
    include_timeout: bool = True,
) -> str:
    """Translate a `run_subagent`/`resume_subagent` result dict into a tool's
    return string. Shared by every subagent-spawning tool's dispatch branch.

    `include_timeout` opts out of the "timeout" status for callers that never
    resume (e.g. `explore_files`, `web_research`), which preserves their
    pre-existing behaviour of falling through to the generic error branch
    instead of exposing a resumable pid.
    """
    status = result["status"]
    if status == "ok":
        return format_handoff_result(result["handoff"])
    if status == "ok_unverified":
        return format_handoff_result(result["handoff"], unverified=True)
    if include_timeout and status == "timeout":
        return json.dumps({"status": "timeout", "pid": result["pid"]})
    return f"[{error_prefix} error] {result.get('message', 'unknown error')}"
