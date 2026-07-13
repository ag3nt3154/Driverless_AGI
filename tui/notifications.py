"""tui/notifications.py — best-effort native Windows toast notifications.

Fire-and-forget: never raises, never blocks the agent loop. Degrades to a
silent no-op if win11toast is missing, the host isn't Windows, or the
underlying WinRT toast call fails for any reason.
"""
from __future__ import annotations

_MAX_MESSAGE_CHARS = 200


def notify(title: str, message: str) -> None:
    """Best-effort Windows toast. Never raises."""
    try:
        import win11toast

        truncated = message if len(message) <= _MAX_MESSAGE_CHARS else message[:_MAX_MESSAGE_CHARS]
        win11toast.notify(title, truncated)
    except Exception:
        pass
