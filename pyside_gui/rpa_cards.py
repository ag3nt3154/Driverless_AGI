"""pyside_gui/rpa_cards.py — parse a halted rpa_run/rpa_patch result into the
data a halt card needs (Subtask 19). Pure: no Qt, no I/O beyond checking for
``halt.png`` next to the run's evidence.

``tools/rpa/_run.py`` emits the halt line verbatim on HALT (and ``_repair.py``
appends the same ``rpa_run`` output after a patch, so a patch result can carry
it too):

    Step `<step_id>` halted: <reason>. Evidence: <run_dir>. Offer the Admiral
    a repair (rpa_repair) — do not start it unasked.

``<reason>`` may itself contain ``". Evidence: "``-like text, so the line is
split on the *last* occurrence of that separator, not the first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["HaltInfo", "parse_rpa_halt"]

_RPA_TOOLS = ("rpa_run", "rpa_patch")
_SUFFIX = "Offer the Admiral a repair (rpa_repair) — do not start it unasked."
_STEP_RE = re.compile(r"Step `([^`]+)` halted: (.*)", re.DOTALL)
_EVIDENCE_SEP = ". Evidence: "


@dataclass(frozen=True)
class HaltInfo:
    name: str
    step: str
    reason: str
    run_dir: Path
    screenshot: "Path | None"


def parse_rpa_halt(tool_name: str, result: object) -> "HaltInfo | None":
    """``None`` for any non-halt result (ok/degraded/cancelled/error) or any
    tool other than rpa_run/rpa_patch."""
    if tool_name not in _RPA_TOOLS or not isinstance(result, str):
        return None

    suffix_at = result.find(_SUFFIX)
    if suffix_at == -1:
        return None
    head = result[:suffix_at].rstrip()
    if head.endswith("."):
        head = head[:-1]

    match = _STEP_RE.search(head)
    if match is None:
        return None
    step, rest = match.group(1), match.group(2)

    sep_at = rest.rfind(_EVIDENCE_SEP)
    if sep_at == -1:
        return None
    reason = rest[:sep_at]
    run_dir = Path(rest[sep_at + len(_EVIDENCE_SEP):])

    name = run_dir.parent.parent.name
    screenshot = run_dir / "halt.png"
    if not screenshot.exists():
        screenshot = None

    return HaltInfo(name=name, step=step, reason=reason, run_dir=run_dir, screenshot=screenshot)
