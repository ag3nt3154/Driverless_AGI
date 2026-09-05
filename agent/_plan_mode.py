"""agent/_plan_mode.py — DEPRECATED, kept for backward compatibility.

Plan mode was removed as a system-level feature in favour of the /plan skill.
The rebuild_for_reload function moved to agent/_reload.py.
"""
from __future__ import annotations

from agent._reload import rebuild_for_reload  # noqa: F401
