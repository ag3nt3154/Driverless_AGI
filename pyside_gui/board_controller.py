"""Main-window board lifecycle and worker coordination."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from agent import DAGI_ROOT
from agent.board_client import BoardError
from pyside_gui.board_downloads import DownloadPool
from pyside_gui.board_runtime import (
    _BACKOFF, StreamListener, error_text, should_render_inline,
    start_board, validate_user_files,
)
from services.message_board.settings import board_settings, resolve_token


def _valid_snapshot(posts) -> tuple[list[dict], bool]:
    """Keep dict posts with integer ids; report whether the response shape was a list."""
    if not isinstance(posts, list):
        return [], False
    return [p for p in posts if isinstance(p, dict) and type(p.get("id")) is int], True


class BoardController(QObject):
    _post_result = Signal(object)

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
        self._post_result.connect(self._on_post_result)
        self.downloads = DownloadPool(self._download)
        bridge = window._bridge
        bridge.board_ready.connect(self._on_ready)
        bridge.board_post.connect(self._on_post)
        bridge.board_status.connect(self._on_status)
        view = window._left_sidebar.board_view
        view.open_file_requested.connect(lambda path: window._left_sidebar.open_file(path, None))

    def start(self) -> None:
        settings = board_settings(getattr(self.window._config, "services", None))
        token = resolve_token()
        state_dir = DAGI_ROOT / ".dagi" / "board"

        def work() -> None:
            try:
                result = start_board(settings.url, token, state_dir=state_dir,
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
        self.runtime = result
        self.window._board_runtime = result
        self.window._board_session = result.session
        view = self.window._left_sidebar.board_view
        view.set_poster(self.post)
        view.set_fetcher(self.downloads.submit)
        self._run_worker(self._load_snapshot, "board-snapshot")

    def _fetch_snapshot(self) -> list | None:
        """Load recent posts, retrying with backoff until success or close."""
        failures = 0
        while not self.cancel.is_set():
            try:
                return self.runtime.client.posts(limit=50)
            except Exception as error:
                delay = _BACKOFF[min(failures, len(_BACKOFF) - 1)]
                failures += 1
                self.window._bridge.board_status.emit(
                    f"Board snapshot failed — {error_text(error)}; retrying in {delay:g}s"
                )
                if self.cancel.wait(delay):
                    return None
        return None

    def _load_snapshot(self) -> None:
        raw = self._fetch_snapshot()
        if raw is None or self.closing:
            return
        posts, is_list = _valid_snapshot(raw)
        if not is_list:
            self.window._bridge.board_status.emit(
                "Board snapshot was malformed; showing live posts"
            )
        for post in posts:
            self.window._bridge.board_post.emit(post)
        after = max((post["id"] for post in posts), default=0)
        listener = StreamListener(
            self.runtime.client, after, self.window._bridge.board_post.emit,
            self.window._bridge.board_status.emit,
        )
        with self._listener_lock:
            if self.closing:
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
        if not isinstance(result, BoardError):
            threading.Thread(target=result.client.close, daemon=True).start()
