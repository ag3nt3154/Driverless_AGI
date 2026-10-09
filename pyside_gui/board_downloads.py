"""Small daemon-worker pool for cancellable board attachment downloads."""
from __future__ import annotations

import queue
import threading
from concurrent.futures import Future


class DownloadPool:
    def __init__(self, work, *, workers: int = 2) -> None:
        self._work = work
        self._queue = queue.Queue()
        self._cancel = threading.Event()
        self._stopped = False
        self._lock = threading.Lock()
        self._threads = [
            threading.Thread(target=self._run, daemon=True, name=f"board-download-{index}")
            for index in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel

    def submit(self, value) -> Future:
        future = Future()
        with self._lock:
            if self._stopped:
                future.cancel()
            else:
                self._queue.put((future, value))
        return future

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._cancel.set()
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    continue
                future, _ = item
                future.cancel()
            for _thread in self._threads:
                self._queue.put(None)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, value = item
            if self._cancel.is_set():
                future.cancel()
                continue
            if future.set_running_or_notify_cancel():
                try:
                    result = self._work(value, self._cancel)
                except BaseException as error:
                    future.set_exception(error)
                else:
                    future.set_result(result)
