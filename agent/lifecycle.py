from __future__ import annotations

import threading
from typing import Callable

from agent.process_state import ProcessStateController

LifecycleCallback = Callable[[], None]
LifecyclePrepare = Callable[[], LifecycleCallback | None]


class LifecyclePublisher:
    """Serialize process/affect lifecycle publication with pause state.

    Accepted process/affect mutations happen while holding the state lock, but
    callbacks are invoked outside it. `pause()` waits only until already-accepted
    callbacks have entered their trampoline; it never waits for callback bodies.
    """

    def __init__(self, process: ProcessStateController) -> None:
        self._process = process
        self._state_lock = threading.RLock()
        self._generation = 0
        self._queue: list[tuple[str, int, LifecyclePrepare]] = []
        self._callback_entries: list[tuple[int, threading.Event]] = []
        self._draining = False
        self.pause_event = threading.Event()
        self.pause_event.set()

    def pause(self) -> None:
        with self._state_lock:
            self.pause_event.clear()
            self._generation += 1
            generation = self._generation
        self.enqueue(
            "paused",
            generation,
            self._prepare_process_state("paused"),
            wait_for_callback_entries=True,
        )

    def resume_thinking(self) -> None:
        with self._state_lock:
            self.pause_event.set()
            self._generation += 1
            generation = self._generation
        self.enqueue("running", generation, self._prepare_process_state("thinking"))

    def publish_running(self, prepare: LifecyclePrepare) -> None:
        with self._state_lock:
            if not self.pause_event.is_set():
                return
            generation = self._generation
        self.enqueue("running", generation, prepare)

    def api_attempt_started(self) -> None:
        self.publish_running(self._prepare_process_state("thinking"))

    def tool_started(self, name: str) -> None:
        self.publish_running(self._prepare_process_state(f"tool:{name}"))

    def tool_bookkeeping_finished(self) -> None:
        self.publish_running(self._prepare_process_state("thinking"))

    def publish_affect_drift(self, controller) -> None:
        self.publish_running(self._prepare_affect_drift(controller))

    def enqueue(
        self,
        state: str,
        generation: int,
        prepare: LifecyclePrepare,
        *,
        wait_for_callback_entries: bool = False,
    ) -> None:
        with self._state_lock:
            entries = (
                self._pending_callback_entries() if wait_for_callback_entries else []
            )
            self._queue.append((state, generation, prepare))
            if self._draining:
                should_drain = False
            else:
                self._draining = True
                should_drain = True
        self._wait_for_callback_entries(entries)
        if should_drain:
            self._drain()

    def _prepare_process_state(self, state: str) -> LifecyclePrepare:
        def prepare() -> LifecycleCallback | None:
            snapshot = self._process.transition_without_notify(state)
            if snapshot is None:
                return None
            return lambda: self._process.emit(snapshot)

        return prepare

    def _prepare_affect_drift(self, controller) -> LifecyclePrepare:
        def prepare() -> LifecycleCallback | None:
            drift_without_notify = getattr(controller, "drift_without_notify", None)
            emit = getattr(controller, "emit", None)
            if not callable(drift_without_notify) or not callable(emit):
                return None
            snapshot = drift_without_notify()
            return lambda: emit(snapshot)

        return prepare

    def _pending_callback_entries(self) -> list[threading.Event]:
        current_thread = threading.get_ident()
        return [
            event
            for thread_id, event in self._callback_entries
            if thread_id != current_thread and not event.is_set()
        ]

    def _wait_for_callback_entries(self, entries: list[threading.Event]) -> None:
        for event in entries:
            event.wait()

    def _mark_callback_pending(self) -> threading.Event:
        event = threading.Event()
        self._callback_entries.append((threading.get_ident(), event))
        return event

    def _mark_callback_entered(self, event: threading.Event) -> None:
        with self._state_lock:
            event.set()
            self._callback_entries = [
                item for item in self._callback_entries if item[1] is not event
            ]

    def before_callback_entry(self) -> None:
        """Test seam for freezing after acceptance but before callback entry."""

    def _start_callback(
        self,
        callback: LifecycleCallback,
        entry_event: threading.Event,
    ) -> None:
        def entered_callback() -> None:
            self._mark_callback_entered(entry_event)
            callback()

        self.before_callback_entry()
        entered_callback()

    def _drain(self) -> None:
        while True:
            try:
                with self._state_lock:
                    if not self._queue:
                        self._draining = False
                        return
                    state, generation, prepare = self._queue.pop(0)
                    should_publish = self._should_publish(state, generation)
                    callback = prepare() if should_publish else None
                    entry = self._mark_callback_pending() if callback is not None else None
            except BaseException:
                with self._state_lock:
                    self._draining = False
                raise
            if not should_publish:
                continue
            try:
                if callback is not None and entry is not None:
                    self._start_callback(callback, entry)
            except BaseException:
                with self._state_lock:
                    self._draining = False
                raise

    def _should_publish(self, state: str, generation: int) -> bool:
        if state == "running":
            return self.pause_event.is_set() and self._generation == generation
        if state == "paused":
            return not self.pause_event.is_set() and self._generation == generation
        return False
