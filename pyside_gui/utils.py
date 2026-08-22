from __future__ import annotations

import time


def format_elapsed(start: float | None) -> str:
    if start is None:
        return "0s"
    secs = int(time.monotonic() - start)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs // 3600}h {(secs % 3600) // 60:02d}m {secs % 60:02d}s"
