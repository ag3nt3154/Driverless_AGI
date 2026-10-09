"""Main-window board lifecycle and worker coordination."""
from __future__ import annotations

import socket
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from agent import DAGI_ROOT
from agent.board_client import BoardClient, BoardError, BoardSession
from pyside_gui.board_downloads import DownloadPool
from pyside_gui.board_runtime import (
    _BACKOFF, StreamListener, error_text, probe, register_runtime, should_render_inline,
    start_board, validate_user_files,
)
from services.message_board.settings import board_settings, resolve_token


def _valid_snapshot(posts) -> tuple[list[dict], bool]:
    """Keep dict posts with integer ids; report whether the response shape was a list."""
    if not isinstance(posts, list):
        return [], False
    return [p for p in posts if isinstance(p, dict) and type(p.get("id")) is int], True


STATE_DIR = DAGI_ROOT / ".dagi" / "board"
CENTRAL_PROBE_MS = 30_000


class BoardController(QObject):
    _post_result = Signal(object)
    _switch_done = Signal(object)  # (url, token, BoardRuntime | BoardError)
    _central_state = Signal(object)  # (url, reachable)

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
        self._error_shown = False
        self._generation = 0  # bumps on every board switch; stale listeners are ignored
        self._token = None
        self.sessions: list[BoardSession] = []  # every agent's session, main first
        self._central_timer = QTimer(self)
        self._central_timer.setInterval(CENTRAL_PROBE_MS)
        self._central_timer.timeout.connect(self._probe_central)
        self._post_result.connect(self._on_post_result)
        self._switch_done.connect(self._on_switched)
        self._central_state.connect(self._on_central_state)
        self.downloads = DownloadPool(self._download)
        bridge = window._bridge
        bridge.board_ready.connect(self._on_ready)
        bridge.board_post.connect(self._on_post)
        bridge.board_status.connect(self._on_status)
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
        view.set_poster(self.post)
        view.set_fetcher(self.downloads.submit)
        view.set_connection(runtime.url, runtime.central_url)
        view.set_central_back(None)
        if runtime.central_url:
            self._central_timer.start()
        else:
            self._central_timer.stop()
        generation = self._generation
        self._run_worker(lambda: self._load_snapshot(generation), "board-snapshot")

    # ── extra agents ────────────────────────────────────────────────────────────────────

    def add_session(self, handle: str) -> BoardSession | None:
        """Bind a spawned agent to the current board; None while the board is offline."""
        if self.runtime is None or self.closing:
            return None
        session = BoardSession(self.runtime.client, handle)
        self.sessions.append(session)
        client = self.runtime.client
        self._run_worker(lambda: client.register(handle, "agent", host=socket.gethostname()),
                         "board-register")
        return session

    def remove_session(self, session: BoardSession) -> None:
        if session in self.sessions[1:]:
            self.sessions.remove(session)

    # ── switching boards ────────────────────────────────────────────────────────────────

    def switch(self, url: str, token=None) -> None:
        """Connect every agent and the view to the board at ``url`` (worker, then UI thread)."""
        if self.closing:
            return
        token = token if token is not None else self._token
        extra = [session.handle for session in self.sessions[1:]]
        self._on_status(f"Connecting to {url}…")

        def work() -> None:
            client = BoardClient(url, token, timeout=10.0)
            try:
                if not probe(client, 5.0):
                    raise BoardError("OFFLINE", "no board is answering there")
                runtime = register_runtime(client, STATE_DIR)
                for handle in extra:
                    client.register(handle, "agent", host=socket.gethostname())
                runtime.url = url
            except Exception as error:
                client.close()
                if not isinstance(error, BoardError):
                    error = BoardError("SWITCH_FAILED", error_text(error))
                self._switch_done.emit((url, token, error))
                return
            self._switch_done.emit((url, token, runtime))

        self._run_worker(work, "board-switch")

    @Slot(object)
    def _on_switched(self, outcome) -> None:
        url, token, result = outcome
        if self.closing:
            self._close_result(result)
            return
        view = self.window._left_sidebar.board_view
        if isinstance(result, BoardError):
            if result.code in ("UNAUTHORIZED", "FORBIDDEN"):
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
        view.clear_posts()
        self._adopt(result)
        if old_runtime is not None:
            threading.Thread(target=self._retire, args=(old_runtime, old_listener),
                             daemon=True, name="board-retire").start()

    @staticmethod
    def _retire(runtime, listener) -> None:
        if listener is not None:
            listener.join()
        runtime.client.close()

    def _probe_central(self) -> None:
        url = self.runtime.central_url if self.runtime is not None else None
        if not url or self.closing:
            return
        token = self._token

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
        if self.closing or self.runtime is None or self.runtime.central_url != url:
            return
        self.window._left_sidebar.board_view.set_central_back(url if reachable else None)

    def _fetch_snapshot(self, runtime) -> list | None:
        """Load recent posts, retrying with backoff until success, close or a switch."""
        failures = 0
        while not self.cancel.is_set() and self.runtime is runtime:
            try:
                return runtime.client.posts(limit=50)
            except Exception as error:
                delay = _BACKOFF[min(failures, len(_BACKOFF) - 1)]
                failures += 1
                self.window._bridge.board_status.emit(
                    f"Board snapshot failed — {error_text(error)}; retrying in {delay:g}s"
                )
                if self.cancel.wait(delay):
                    return None
        return None

    def _load_snapshot(self, generation: int | None = None) -> None:
        generation = self._generation if generation is None else generation
        runtime = self.runtime
        raw = self._fetch_snapshot(runtime)
        if raw is None or self.closing or generation != self._generation:
            return
        posts, is_list = _valid_snapshot(raw)
        if not is_list:
            self.window._bridge.board_status.emit(
                "Board snapshot was malformed; showing live posts"
            )
        for post in posts:
            self.window._bridge.board_post.emit(post)
        after = max((post["id"] for post in posts), default=0)
        bridge = self.window._bridge

        def current() -> bool:
            return generation == self._generation

        listener = StreamListener(
            runtime.client, after,
            lambda post: current() and bridge.board_post.emit(post),
            lambda text: current() and bridge.board_status.emit(text),
        )
        with self._listener_lock:
            if self.closing or not current():
                return
            self.listener = listener
            self.window._board_listener = listener
            listener.start()

    @Slot(object)
    def _on_post(self, post: dict) -> None:
        if self.closing or not isinstance(post, dict):
            return
        self.window._left_sidebar.board_view.add_post(post)
        if self.runtime is None:
            return
        memes = self.window._left_sidebar.board_view.meme_map
        path = should_render_inline(post, self.runtime.session.handle, memes)
        if path is not None:
            self.window._conversation.append_emote(
                post["meme"], str(path), post.get("text", ""), post.get("created_at", "")
            )

    @Slot(str)
    def _on_status(self, text: str) -> None:
        if not self.closing:
            self._error_shown = False
            self.window._left_sidebar.board_view.set_status(text)

    def _on_status_error(self, text: str) -> None:
        self._on_status(text)
        self._error_shown = True

    @Slot(object)
    def _on_post_result(self, error) -> None:
        """Show a poster failure, or clear only a poster error after a later success."""
        if error is not None:
            self._on_status_error(error)
        elif self._error_shown:
            self._on_status("")

    def post(self, text: str, paths: list[Path]) -> bool:
        """Start posting; False means refused up front and the composer should keep input."""
        accepted, errors = validate_user_files(paths)
        if errors:
            self._on_status_error(errors[0])
            return False

        def work() -> None:
            try:
                attachments = [
                    self.runtime.client.upload(self.runtime.user_handle, path)["id"]
                    for path in accepted
                ]
                self.runtime.client.post(
                    self.runtime.user_handle, text, attachments=attachments,
                )
            except Exception as error:
                self._post_result.emit(error_text(error))
            else:
                self._post_result.emit(None)

        self._run_worker(work, "board-poster")
        return True

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

        def guarded() -> None:
            try:
                target()
            except Exception as error:
                self.window._bridge.board_status.emit(error_text(error))
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
        with self._listener_lock:
            self.closing = True
            listener = self.listener
        self.cancel.set()
        self.downloads.stop()
        if listener is not None:
            listener.stop()
        view = self.window._left_sidebar.board_view
        view.set_poster(None)
        view.close_downloads()
        threading.Thread(target=self._cleanup, daemon=True, name="board-cleanup").start()

    def _cleanup(self) -> None:
        # Download-pool jobs are not counted in _active: fetch_attachment uses its own
        # async client and observes the pool's cancel event, so closing this sync client
        # cannot race an in-flight download.
        if self.listener is not None:
            self.listener.join()
        self._idle.wait()
        if self.runtime is not None:
            self.runtime.client.close()

    @staticmethod
    def _close_result(result) -> None:
        if isinstance(result, tuple):
            result = result[-1]
        if not isinstance(result, BoardError):
            threading.Thread(target=result.client.close, daemon=True).start()
