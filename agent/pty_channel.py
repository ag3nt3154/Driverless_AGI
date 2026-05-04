"""agent/pty_channel.py — ConPTY wrapper for subagent terminal processes."""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

SENTINEL = "<<<DAGI_DONE>>>"
EXIT_CMD = "<<<DAGI_EXIT>>>"

# Comprehensive ANSI/VT escape sequence stripper:
#   C1 Fe sequences: ESC + single char in [@-_]
#   CSI sequences:   ESC [ <param bytes [0-?]> <intermediate bytes [ -/]> <final byte [@-~]>
#   OSC sequences:   ESC ] ... BEL or ESC \
#   Bare CR for PTY line endings
_ANSI_RE = re.compile(
    r"\x1b(?:"
    r"[@-Z\\-_]|"
    r"\[[0-?]*[ -/]*[@-~]|"
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r")|\r"
)


class PtyTimeoutError(TimeoutError):
    pass


class PtyChannel:
    """Wraps a pywinpty PtyProcess with a background reader, log tee, and sentinel detection.

    The reader thread runs as a daemon and continuously pulls output from the
    PTY into an in-memory buffer AND tees it to a log file. The parent process
    calls read_until_sentinel() which blocks (spin-sleeping at 50ms) until the
    sentinel string appears in the buffer, then returns the preceding text
    with ANSI codes stripped.
    """

    def __init__(
        self,
        argv: list[str],
        log_file: Path,
        dimensions: tuple[int, int] = (50, 220),
    ) -> None:
        from winpty import PtyProcess

        self._log_file = log_file
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("", encoding="utf-8")

        self._proc = PtyProcess.spawn(argv, dimensions=dimensions)
        self._buffer = ""
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._reader, daemon=True, name="pty-reader")
        self._thread.start()

    # ── Public API ────────────────────────────────────────────────────────────

    def write(self, text: str) -> None:
        """Send text to the subagent's stdin.

        On Windows ConPTY the line discipline requires CR+LF to trigger line
        delivery, so bare LF is normalized to CRLF before sending.
        """
        self._proc.write(text.replace("\n", "\r\n"))

    def read_until_sentinel(self, timeout: float = 300.0) -> str:
        """Block until SENTINEL appears in output. Returns clean text before it.

        ANSI escape codes are stripped from the returned result.
        Raises PtyTimeoutError if the sentinel does not appear within timeout seconds.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                idx = self._buffer.find(SENTINEL)
                if idx >= 0:
                    result = self._buffer[:idx]
                    self._buffer = self._buffer[idx + len(SENTINEL):]
                    return _ANSI_RE.sub("", result).strip()
            time.sleep(0.05)
        raise PtyTimeoutError(f"Sentinel '{SENTINEL}' not seen within {timeout}s")

    def isalive(self) -> bool:
        return self._proc.isalive()

    def terminate(self, force: bool = False) -> None:
        try:
            self._proc.terminate(force=force)
        except Exception:
            pass

    # ── Background reader ─────────────────────────────────────────────────────

    def _reader(self) -> None:
        """Read PTY output continuously, tee to log file, append to in-memory buffer."""
        with open(self._log_file, "a", encoding="utf-8", errors="replace") as fh:
            while self._proc.isalive():
                try:
                    chunk = self._proc.read(4096)
                except EOFError:
                    break
                if not chunk:
                    continue
                fh.write(chunk)
                fh.flush()
                with self._lock:
                    self._buffer += chunk
