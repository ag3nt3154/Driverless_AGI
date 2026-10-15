"""Message board SSE parsing and the reconnecting stream listener thread."""
from __future__ import annotations

import json
import threading

_BACKOFF = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)


_SSE_EVENTS = ("post", "purge")


def _decode_event(event: str | None, data: list[str]) -> tuple[str, dict] | None:
    if event not in _SSE_EVENTS or not data:
        return None
    try:
        value = json.loads("\n".join(data))
    except (json.JSONDecodeError, TypeError):
        return None
    return (event, value) if isinstance(value, dict) else None


def parse_sse_events(lines):
    """Yield ``(event, payload)`` for each well-formed ``post`` or ``purge`` SSE event."""
    event = None
    data = []
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            value = _decode_event(event, data)
            if value is not None:
                yield value
            event, data = None, []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[6:].lstrip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    value = _decode_event(event, data)
    if value is not None:
        yield value


def parse_sse(lines):
    """Yield only the ``post`` payloads of an SSE line stream."""
    for event, payload in parse_sse_events(lines):
        if event == "post":
            yield payload


class StreamListener(threading.Thread):
    def __init__(self, client, after: int, on_post, on_status, *, backoff=_BACKOFF,
                 on_purge=None) -> None:
        super().__init__(daemon=True)
        self.client = client
        self.after = after
        self.on_post = on_post
        self.on_status = on_status
        self.on_purge = on_purge
        self.backoff = tuple(backoff) or (30.0,)
        self._stop_event = threading.Event()
        self._active = None
        self._active_lock = threading.Lock()

    def stop(self) -> None:
        self._stop_event.set()
        with self._active_lock:
            active = self._active
        if active is not None:
            active.close()

    def _activate(self, active) -> bool:
        with self._active_lock:
            if self._stop_event.is_set():
                return False
            self._active = active
            return True

    def _clear_active(self) -> None:
        with self._active_lock:
            self._active = None

    def _listen_once(self) -> bool:
        """Consume one connection; True when it delivered a new post.

        Purges are forwarded but never count as delivery and never move ``after``: the board
        replays every purge on each connect, so counting them would reset the reconnect
        backoff on every flapping connection.
        """
        delivered = False
        with self.client.stream(self.after) as lines:
            if not self._activate(lines):
                lines.close()
                return delivered
            if self._stop_event.is_set():
                lines.close()
                return delivered
            self.on_status("connected")
            for event, post in parse_sse_events(lines):
                if self._stop_event.is_set():
                    return delivered
                if event == "purge":
                    if self.on_purge is not None:
                        self.on_purge(post)
                    continue
                post_id = post.get("id")
                if type(post_id) is int and post_id > self.after:
                    self.after = post_id
                    self.on_post(post)
                    delivered = True
            if not self._stop_event.is_set():
                self.on_status("reconnecting: stream ended")
        return delivered

    def run(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            try:
                if self._listen_once():
                    failures = 0
            except Exception as error:
                if self._stop_event.is_set():
                    return
                reason = str(error) or type(error).__name__
                self.on_status(f"reconnecting: {reason}")
            finally:
                self._clear_active()
            if self._stop_event.is_set():
                return
            delay = self.backoff[min(failures, len(self.backoff) - 1)]
            failures += 1
            self._stop_event.wait(delay)
