"""Main-window board lifecycle and worker coordination."""
from __future__ import annotations

import socket
import threading
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from agent import DAGI_ROOT
from agent.board_client import BoardClient, BoardError, BoardSession, new_key
from pyside_gui.board_downloads import DownloadPool
from pyside_gui.board_runtime import (
    _BACKOFF, StreamListener, error_text, probe, register_runtime, should_render_inline,
    start_board,
)
from services.message_board.settings import board_settings, resolve_token


def _valid_snapshot(posts) -> tuple[list[dict], bool]:
    """Keep dict posts with integer ids; report whether the response shape was a list."""
    if not isinstance(posts, list):
        return [], False
    return [p for p in posts if isinstance(p, dict) and type(p.get("id")) is int], True


STATE_DIR = DAGI_ROOT / ".dagi" / "board"
CENTRAL_PROBE_MS = 30_000
PRESENCE_MS = 30_000  # re-register every agent so the board shows it online (90 s window)


class BoardController(QObject):
    _switch_done = Signal(object)  # (attempt, url, token, BoardRuntime | BoardError)
    _central_state = Signal(object)  # (url, reachable)
    _snapshot = Signal(object)  # (generation, posts, live-after id)

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.closing = False
        self.cancel = threading.Event()
        self.runtime = None
        self.listener = None
        self._listener_lock = threading.Lock()
        self._active = 0
        self._active_lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._generation = 0  # bumps on every board switch; stale listeners are ignored
        self._token = None
        self._live_after: int | None = None  # posts above this id are live (may wake agents)
        self._switch_attempt = 0
        self._switch_in_flight: tuple[int, str, bool] | None = None
        self._auto_switch_blocked_urls: set[str] = set()
        self.sessions: list[BoardSession] = []  # every agent's session, main first
        self._central_timer = QTimer(self)
        self._central_timer.setInterval(CENTRAL_PROBE_MS)
        self._central_timer.timeout.connect(self._probe_central)
        self._presence_timer = QTimer(self)
        self._presence_timer.setInterval(PRESENCE_MS)
        self._presence_timer.timeout.connect(self._heartbeat)
        self._switch_done.connect(self._on_switched)
        self._central_state.connect(self._on_central_state)
        self._snapshot.connect(self._on_snapshot)
        self.downloads = DownloadPool(self._download)
        bridge = window._bridge
        bridge.board_ready.connect(self._on_ready)
        # Board events carry the generation that produced them: a switch cannot withdraw
        # signals already queued, so the GUI slots drop anything from an earlier board.
        bridge.board_post.connect(self._on_post_event)
        bridge.board_status.connect(self._on_status_event)
        bridge.board_purge.connect(self._on_purge_event)
        view = window._left_sidebar.board_view
        view.open_file_requested.connect(lambda path: window._left_sidebar.open_file(path, None))
        view.connect_requested.connect(self.switch)

    def start(self) -> None:
        settings = board_settings(getattr(self.window._config, "services", None))
        token = self._token = resolve_token()

        def work() -> None:
            try:
                result = start_board(settings.url, token, state_dir=STATE_DIR,
                                     bind=settings.bind, cancel=self.cancel)
            except BoardError as error:
                result = error
            except Exception as error:
                result = BoardError("START_FAILED", str(error) or type(error).__name__)
            self.window._bridge.board_ready.emit(result)

        threading.Thread(target=work, daemon=True, name="board-startup").start()

    @Slot(object)
    def _on_ready(self, result) -> None:
        if self.closing:
            self._close_result(result)
            return
        if isinstance(result, BoardError):
            self._on_status(f"Board offline — {result.message}")
            return
        self.sessions = [result.session]
        self._adopt(result)

    def _adopt(self, runtime) -> None:
        """Make ``runtime`` the live board: wire the view, show the address, load posts."""
        self.runtime = runtime
        self.window._board_runtime = runtime
        self.window._board_session = self.sessions[0]
        view = self.window._left_sidebar.board_view
        view.set_fetcher(self.downloads.submit)
        view.set_connection(runtime.url, runtime.central_url)
        view.set_central_available(runtime.central_url or "", False)
        if runtime.temp is not None:
            self._central_timer.start()
        else:
            self._central_timer.stop()
        self._presence_timer.start()
        hook = getattr(self.window, "_on_board_ready", None)
        if hook is not None:
            hook()
        generation = self._generation
        self._run_worker(lambda: self._load_snapshot(generation, runtime), "board-snapshot")

    # ── extra agents ────────────────────────────────────────────────────────────────────

    def add_session(self, handle: str) -> BoardSession | None:
        """Bind a spawned agent to the current board; None while the board is offline."""
        if self.runtime is None or self.closing:
            return None
        session = BoardSession(self.runtime.client, handle, new_key())
        self.sessions.append(session)
        client = self.runtime.client
        self._run_worker(lambda: client.register(handle, "agent", host=socket.gethostname(),
                                                 key=session.key), "board-register")
        return session

    def remove_session(self, session: BoardSession) -> None:
        if session in self.sessions[1:]:
            self.sessions.remove(session)

    def _heartbeat(self) -> None:
        """Keep every agent online on the board; closed agents drop off after 90 s."""
        if self.runtime is None or self.closing:
            return
        client = self.runtime.client
        members = [(session.handle, session.key) for session in self.sessions]

        def work() -> None:
            host = socket.gethostname()
            for handle, key in members:
                client.register(handle, "agent", host=host, key=key)

        self._run_worker(work, "board-presence")

    # ── switching boards ────────────────────────────────────────────────────────────────

    def switch(self, url: str, token=None, *, _automatic: bool = False) -> None:
        """Connect every agent and the view to the board at ``url`` (worker, then UI thread)."""
        if self.closing or self._switch_in_flight is not None:
            return
        if not _automatic:
            self._auto_switch_blocked_urls.discard(url)
        self._switch_attempt += 1
        attempt = self._switch_attempt
        self._switch_in_flight = (attempt, url, _automatic)
        token = token if token is not None else self._token
        extra = [(session.handle, session.key) for session in self.sessions[1:]]
        self._on_status(f"Connecting to {url}…")

        def work() -> None:
            client = None
            try:
                client = BoardClient(url, token, timeout=10.0)
                if not probe(client, 5.0):
                    raise BoardError("OFFLINE", "no board is answering there")
                runtime = register_runtime(client, STATE_DIR)
                for handle, key in extra:
                    client.register(handle, "agent", host=socket.gethostname(), key=key)
                runtime.url = url
            except Exception as error:
                if client is not None:
                    client.close()
                if not isinstance(error, BoardError):
                    error = BoardError("SWITCH_FAILED", error_text(error))
                self._switch_done.emit((attempt, url, token, error))
                return
            self._switch_done.emit((attempt, url, token, runtime))

        self._run_worker(work, "board-switch")

    @Slot(object)
    def _on_switched(self, outcome) -> None:
        attempt, url, token, result = outcome
        active = self._switch_in_flight
        if active is None or active[0] != attempt:
            if result is not self.runtime:
                self._close_result(result)
            return
        self._switch_in_flight = None
        automatic = active[2]
        if self.closing:
            self._close_result(result)
            return
        view = self.window._left_sidebar.board_view
        if isinstance(result, BoardError):
            if result.code in ("UNAUTHORIZED", "FORBIDDEN"):
                if automatic:
                    self._auto_switch_blocked_urls.add(url)
                self._on_status(f"{url} needs a token.")
                view.ask_token(url)
            else:
                self._on_status(f"Cannot connect to {url} — {result.message}")
            return
        old_runtime = self.runtime
        with self._listener_lock:
            self._generation += 1
            old_listener, self.listener = self.listener, None
            self.window._board_listener = None
        if old_listener is not None:
            old_listener.stop()
        if not self.sessions:
            self.sessions = [result.session]
        for session in self.sessions:
            session.rebind(result.client)
        result.session = self.sessions[0]
        self._token = token
        self._live_after = None
        view.clear_posts()
        self._adopt(result)
        if old_runtime is not None:
            threading.Thread(target=self._retire, args=(old_runtime, old_listener),
                             daemon=True, name="board-retire").start()
            if getattr(old_runtime, "temp", None) is not None:
                if old_runtime.central_url == url:
                    self._on_status(
                        f"Switched to central board {url}; temp board posts were discarded."
                    )
                else:
                    self._on_status(f"Switched to {url}; temp board posts were discarded.")

    @staticmethod
    def _retire(runtime, listener) -> None:
        if listener is not None:
            listener.join()
        temp = getattr(runtime, "temp", None)
        try:
            runtime.client.close()
        finally:
            if temp is not None:
                temp.close()

    def _probe_central(self) -> None:
        url = self.runtime.central_url if self.runtime is not None and self.runtime.temp else None
        if not url or self.closing:
            return
        token = resolve_token()

        def work() -> None:
            client = BoardClient(url, token, timeout=3.0)
            try:
                reachable = probe(client, 3.0)
            except BoardError:
                reachable = True  # something answers there; switching reports the details
            finally:
                client.close()
            self._central_state.emit((url, reachable))

        self._run_worker(work, "board-central-probe")

    @Slot(object)
    def _on_central_state(self, outcome) -> None:
        url, reachable = outcome
        if (self.closing or self.runtime is None or self.runtime.temp is None
                or self.runtime.central_url != url):
            return
        self.window._left_sidebar.board_view.set_central_available(url, reachable)
        if reachable and not self._switch_in_flight and url not in self._auto_switch_blocked_urls:
            self.switch(url, resolve_token(), _automatic=True)

    def _fetch_snapshot(self, runtime, generation: int) -> list | None:
        """Load recent posts, retrying with backoff until success, close or a switch."""
        failures = 0
        while not self.cancel.is_set() and self.runtime is runtime:
            try:
                return runtime.client.posts(limit=50)
            except Exception as error:
                delay = _BACKOFF[min(failures, len(_BACKOFF) - 1)]
                failures += 1
                self.window._bridge.board_status.emit((
                    generation,
                    f"Board snapshot failed — {error_text(error)}; retrying in {delay:g}s",
                ))
                if self.cancel.wait(delay):
                    return None
        return None

    def _load_snapshot(self, generation: int | None = None, runtime=None) -> None:
        generation = self._generation if generation is None else generation
        runtime = self.runtime if runtime is None else runtime
        raw = self._fetch_snapshot(runtime, generation)
        if raw is None or self.closing or generation != self._generation:
            return
        posts, is_list = _valid_snapshot(raw)
        if not is_list:
            self.window._bridge.board_status.emit(
                (generation, "Board snapshot was malformed; showing live posts")
            )
        after = max((post["id"] for post in posts), default=0)
        # One event, so the posts and the live cursor are committed together on the GUI
        # thread, and only if the board has not switched meanwhile. It is queued before the
        # listener starts, so it lands ahead of every streamed post.
        self._snapshot.emit((generation, posts, after))
        bridge = self.window._bridge

        def current() -> bool:
            return generation == self._generation

        listener = StreamListener(
            runtime.client, after,
            lambda post: current() and bridge.board_post.emit((generation, post)),
            lambda text: current() and bridge.board_status.emit((generation, text)),
            on_purge=lambda purge: current() and bridge.board_purge.emit((generation, purge)),
        )
        with self._listener_lock:
            if self.closing or not current():
                return
            self.listener = listener
            self.window._board_listener = listener
            listener.start()

    def _current_event(self, event) -> bool:
        """True for a (generation, payload) event from the live board while still open."""
        return (not self.closing and isinstance(event, tuple) and len(event) >= 2
                and event[0] == self._generation)

    @Slot(object)
    def _on_snapshot(self, event) -> None:
        if not self._current_event(event):
            return
        _generation, posts, after = event
        view = self.window._left_sidebar.board_view
        for post in posts:
            view.add_post(post)  # snapshot: board panel only, so a new chat opens empty
        self._live_after = after

    @Slot(object)
    def _on_post_event(self, event) -> None:
        if self._current_event(event):
            self._on_post(event[1])

    @Slot(object)
    def _on_status_event(self, event) -> None:
        if self._current_event(event):
            self._on_status(event[1])

    @Slot(object)
    def _on_purge_event(self, event) -> None:
        if self._current_event(event):
            self.window._left_sidebar.board_view.remove_purged(event[1])

    def _on_post(self, post: dict) -> None:
        if self.closing or not isinstance(post, dict):
            return
        self.window._left_sidebar.board_view.add_post(post)
        if self.runtime is None:
            return
        live = self._live_after is not None and type(post.get("id")) is int             and post["id"] > self._live_after
        hook = getattr(self.window, "_on_board_mention", None)
        if live and post.get("mentions") and hook is not None:
            hook(post)
        if not live:
            return  # startup snapshot: board panel only, so a new chat opens empty
        memes = self.window._left_sidebar.board_view.meme_map
        for handle, conversation in self._conversations():
            path = should_render_inline(post, handle, memes)
            if path is not None:
                conversation.append_emote(
                    post["meme"], str(path), post.get("text", ""), post.get("created_at", "")
                )

    def _conversations(self):
        """(board handle, conversation) for each agent; an agent's memes show in its own chat."""
        sessions = getattr(self.window, "_sessions", None)
        if sessions is None:
            return [(self.runtime.session.handle, self.window._conversation)]
        return [(s._board_session.handle, s._conversation)
                for s in sessions if s._board_session is not None]

    def _on_status(self, text: str) -> None:
        if not self.closing:
            self.window._left_sidebar.board_view.set_status(text)

    def _download(self, attachment_id: str, cancel) -> Path:
        if self.runtime is None:
            raise BoardError("OFFLINE", "message board is not ready")
        _metadata, path = self.runtime.client.fetch_attachment(
            attachment_id, project_root=DAGI_ROOT, cancel=cancel, deadline_s=10.0,
        )
        return path

    def _run_worker(self, target, name: str) -> None:
        with self._active_lock:
            self._active += 1
            self._idle.clear()
        generation = self._generation

        def guarded() -> None:
            try:
                target()
            except Exception as error:
                self.window._bridge.board_status.emit((generation, error_text(error)))
            finally:
                with self._active_lock:
                    self._active -= 1
                    if self._active == 0:
                        self._idle.set()

        try:
            threading.Thread(target=guarded, daemon=True, name=name).start()
        except Exception:
            with self._active_lock:
                self._active -= 1
                if self._active == 0:
                    self._idle.set()
            raise

    def close(self) -> None:
        self._central_timer.stop()
        self._presence_timer.stop()
        with self._listener_lock:
            self.closing = True
            listener = self.listener
        self.cancel.set()
        self.downloads.stop()
        if listener is not None:
            listener.stop()
        view = self.window._left_sidebar.board_view
        view.close_downloads()
        threading.Thread(target=self._cleanup, daemon=True, name="board-cleanup").start()

    def _cleanup(self) -> None:
        # Download-pool jobs are not counted in _active: fetch_attachment uses its own
        # async client and observes the pool's cancel event, so closing this sync client
        # cannot race an in-flight download.
        listener = self.listener
        if listener is not None:
            listener.join()
        self._idle.wait()
        if self.runtime is not None:
            temp = getattr(self.runtime, "temp", None)
            try:
                self.runtime.client.close()
            finally:
                if temp is not None:
                    temp.close()

    @staticmethod
    def _close_result(result) -> None:
        if isinstance(result, tuple):
            result = result[-1]
        if not isinstance(result, BoardError):
            def close() -> None:
                temp = getattr(result, "temp", None)
                try:
                    result.client.close()
                finally:
                    if temp is not None:
                        temp.close()
            threading.Thread(target=close, daemon=True, name="board-late-retire").start()
