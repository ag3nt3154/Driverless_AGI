from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from agent.affect import AffectConfig, AffectController
from agent.dynamic_context import build_dynamic_context
from agent.expression_assets import ProcessStateLibrary, VadLibrary
from agent.process_state import ProcessStateController

LifecycleCallback = Callable[[], None]
LifecyclePrepare = Callable[[], LifecycleCallback | None]
LifecycleItem = tuple[str, int, LifecyclePrepare]
AcceptedCallback = tuple[LifecycleCallback, threading.Event]


def load_vad_library(dagi_root: Path) -> VadLibrary:
    """Load the current VAD library, falling back to text when assets are absent."""
    emotes_root = dagi_root / ".dagi" / "emotes"
    return VadLibrary.load(
        emotes_root / "vad",
        emotes_root / "default.md",
    )


def ensure_affect_controller(
    tracker: Any,
    config: Any,
    dagi_root: Path,
    callbacks: Any,
    initial_affect: Any,
) -> None:
    """Bind the root affect controller early enough for main registry construction."""
    if tracker.affect_controller is not None:
        tracker.affect_controller.set_listener(callbacks.on_affect_changed)
        return
    affect_config = AffectConfig(
        drift_pull=config.affect_drift_pull,
        drift_noise=config.affect_drift_noise,
        emote_hysteresis=config.affect_emote_hysteresis,
    )
    controller = AffectController(
        load_vad_library(dagi_root),
        config=affect_config,
        baseline=initial_affect.baseline if initial_affect else None,
        current=initial_affect.current if initial_affect else None,
        current_emote_id=initial_affect.emote_id if initial_affect else None,
        record=tracker.record_affect,
        on_change=callbacks.on_affect_changed,
    )
    tracker.bind_affect_controller(controller)


def load_process_library(dagi_root: Path) -> ProcessStateLibrary:
    emotes_root = dagi_root / ".dagi" / "emotes"
    return ProcessStateLibrary.load(
        emotes_root / "states",
        emotes_root / "default.md",
    )


def build_dynamic_context_with_affect(config: Any, controller: Any) -> str:
    affect_line = controller.context_line() if controller is not None else None
    if not isinstance(affect_line, str):
        affect_line = None
    return build_dynamic_context(config, affect_line)


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
        self._queue: list[LifecycleItem] = []
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
                accepted = self._dequeue_accepted_callback()
            except BaseException:
                self._clear_draining()
                raise
            if accepted is None:
                return
            callback, entry = accepted
            try:
                self._start_callback(callback, entry)
            except BaseException:
                self._clear_draining()
                raise

    def _dequeue_accepted_callback(self) -> AcceptedCallback | None:
        while True:
            item = self._pop_next_item()
            if item is None:
                return None
            state, generation, prepare = item
            callback = self._accept_callback(state, generation, prepare)
            if callback is not None:
                return callback

    def _pop_next_item(self) -> LifecycleItem | None:
        with self._state_lock:
            if not self._queue:
                self._draining = False
                return None
            return self._queue.pop(0)

    def _accept_callback(
        self,
        state: str,
        generation: int,
        prepare: LifecyclePrepare,
    ) -> AcceptedCallback | None:
        with self._state_lock:
            if not self._should_publish(state, generation):
                return None
            callback = prepare()
            if callback is None:
                return None
            return callback, self._mark_callback_pending()

    def _clear_draining(self) -> None:
        with self._state_lock:
            self._draining = False

    def _should_publish(self, state: str, generation: int) -> bool:
        if state == "running":
            return self.pause_event.is_set() and self._generation == generation
        if state == "paused":
            return not self.pause_event.is_set() and self._generation == generation
        return False
