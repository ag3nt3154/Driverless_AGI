"""rpa/hotkey.py — a physical Esc anywhere stops a running replay.

dagi's GUI handles Esc only while one of its own windows has focus, but during a
replay the focus is on the app being driven (and switching to dagi makes the
foreground guard refuse the next input). `EscWatcher` installs a Windows
low-level keyboard hook for the duration of a run: a physical Esc key-down calls
`on_escape` and is swallowed, so the driven app does not react to it. Keys the
replay itself sends are injected and are ignored. Elsewhere it is a no-op.
"""
from __future__ import annotations

import ctypes
import sys
import threading
from typing import Callable

_WH_KEYBOARD_LL = 13
_WM_KEYDOWN = 0x0100
_WM_SYSKEYDOWN = 0x0104
_WM_QUIT = 0x0012
_VK_ESCAPE = 0x1B
_LLKHF_INJECTED = 0x10


def is_physical_escape(vk_code: int, flags: int, message: int) -> bool:
    """A user's Esc key-down (not one injected by SendInput/SendKeys)."""
    return (
        vk_code == _VK_ESCAPE
        and message in (_WM_KEYDOWN, _WM_SYSKEYDOWN)
        and not flags & _LLKHF_INJECTED
    )


class EscWatcher:
    """Context manager: while active, a physical Esc anywhere calls `on_escape()`."""

    def __init__(self, on_escape: Callable[[], None]) -> None:
        self._on_escape = on_escape
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()

    def __enter__(self) -> "EscWatcher":
        if sys.platform == "win32":
            self._thread = threading.Thread(target=self._run, name="rpa-esc-hook", daemon=True)
            self._thread.start()
            self._ready.wait(2.0)
        return self

    def __exit__(self, *exc) -> None:
        if self._thread is not None and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)
            self._thread.join(2.0)

    def _run(self) -> None:
        from ctypes import wintypes

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
            ]

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, proc_type, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        def proc(n_code: int, w_param: int, l_param: int) -> int:
            if n_code == 0:
                kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if is_physical_escape(kb.vkCode, kb.flags, w_param):
                    try:
                        self._on_escape()
                    finally:
                        return 1  # swallow: the driven app must not also act on it
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        callback = proc_type(proc)  # keep a reference for the hook's lifetime
        self._thread_id = kernel32.GetCurrentThreadId()
        hook = user32.SetWindowsHookExW(_WH_KEYBOARD_LL, callback, kernel32.GetModuleHandleW(None), 0)
        self._ready.set()
        if not hook:
            return
        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnhookWindowsHookEx(hook)
