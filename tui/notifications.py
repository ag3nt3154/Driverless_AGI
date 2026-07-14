"""tui/notifications.py — best-effort native Windows toast notifications.

Fire-and-forget: never raises, never blocks the agent loop. Degrades to a
silent no-op if win11toast is missing, the host isn't Windows, or the
underlying WinRT toast call fails for any reason.
"""
from __future__ import annotations

_MAX_MESSAGE_CHARS = 200


def _tui_window_is_foreground() -> bool:
    """True if this console window currently has OS focus."""
    import ctypes

    console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if not console_hwnd:
        return False
    return ctypes.windll.user32.GetForegroundWindow() == console_hwnd


def notify(title: str, message: str) -> None:
    """Best-effort Windows toast. Never raises. Skips if the TUI window is focused."""
    try:
        if _tui_window_is_foreground():
            return
    except Exception:
        pass

    try:
        import win11toast

        truncated = message if len(message) <= _MAX_MESSAGE_CHARS else message[:_MAX_MESSAGE_CHARS]
        win11toast.notify(title, truncated)
    except Exception:
        pass
