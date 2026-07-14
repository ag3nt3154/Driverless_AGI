"""tests/test_tui_notifications.py — notify() best-effort Windows toast wrapper."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from tui.notifications import notify


class TestNotify:
    def test_calls_win11toast_with_title_and_message(self):
        fake_win11toast = MagicMock()
        with patch("tui.notifications._tui_window_is_foreground", return_value=False), \
             patch.dict(sys.modules, {"win11toast": fake_win11toast}):
            notify("DAGI has a question", "What color should the button be?")

        fake_win11toast.notify.assert_called_once_with(
            "DAGI has a question", "What color should the button be?"
        )

    def test_truncates_long_message_to_200_chars(self):
        fake_win11toast = MagicMock()
        long_message = "x" * 500
        with patch("tui.notifications._tui_window_is_foreground", return_value=False), \
             patch.dict(sys.modules, {"win11toast": fake_win11toast}):
            notify("Title", long_message)

        args, _ = fake_win11toast.notify.call_args
        assert len(args[1]) <= 200

    def test_swallows_exception_from_notify_call(self):
        fake_win11toast = MagicMock()
        fake_win11toast.notify.side_effect = RuntimeError("WinRT toast failed")
        with patch("tui.notifications._tui_window_is_foreground", return_value=False), \
             patch.dict(sys.modules, {"win11toast": fake_win11toast}):
            # Must not raise.
            notify("Title", "Message")

    def test_swallows_missing_dependency(self):
        with patch("tui.notifications._tui_window_is_foreground", return_value=False), \
             patch.dict(sys.modules, {"win11toast": None}):
            # sys.modules[name] = None forces `import win11toast` to raise ImportError.
            # Must not raise.
            notify("Title", "Message")

    def test_skips_notification_when_tui_window_is_foreground(self):
        fake_win11toast = MagicMock()
        with patch("tui.notifications._tui_window_is_foreground", return_value=True), \
             patch.dict(sys.modules, {"win11toast": fake_win11toast}):
            notify("Title", "Message")

        fake_win11toast.notify.assert_not_called()

    def test_sends_notification_when_foreground_check_raises(self):
        # A failure to determine window state must fail open (still notify),
        # not silently swallow real notifications.
        fake_win11toast = MagicMock()
        with patch(
            "tui.notifications._tui_window_is_foreground",
            side_effect=RuntimeError("no ctypes"),
        ), patch.dict(sys.modules, {"win11toast": fake_win11toast}):
            notify("Title", "Message")

        fake_win11toast.notify.assert_called_once_with("Title", "Message")
