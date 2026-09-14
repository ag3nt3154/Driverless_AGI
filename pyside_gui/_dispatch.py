"""Submission routing + agent dispatch, extracted from app.py to stay under
its line cap.

These are free functions rather than a mixin: each takes the ``DagiMainWindow``
instance (``win``) as its first argument and reaches into its attributes the
same way the original methods did. app.py keeps thin wrapper methods (some
tests call ``DagiMainWindow._on_input_submitted``/``_agent_work`` etc. as
unbound functions against a stand-in object) that just forward here.
"""
from __future__ import annotations

import threading
import time
import traceback

from agent.image_assets import AssetError, ImageAssetStore, ImageRef
from agent.loop import AgentLoop
from agent.user_input import UserSubmission

from pyside_gui.bridge import worker_log


def _as_submission(task: str | UserSubmission) -> UserSubmission:
    return task if isinstance(task, UserSubmission) else UserSubmission(text=task)


def _display_text(task: str | UserSubmission) -> str:
    """Text to show in the conversation bubble, with an image-count suffix."""
    submission = _as_submission(task)
    n = len(submission.images)
    if not n:
        return submission.text
    suffix = f"[{n} image{'s' if n != 1 else ''}]"
    return f"{submission.text} {suffix}".strip()


def _append_user_with_images(win, submission: UserSubmission) -> None:
    """Append a user message to the conversation, with image thumbnails when present.

    Falls back to the plain text bubble (with an "[N images]" suffix) if
    resolving the image files fails, so a broken asset store never blocks
    the user from seeing their own message or from continuing to type.
    """
    if not submission.images:
        win._conversation.append_user_message(submission.text)
        return
    try:
        store = ImageAssetStore(win._config.project_path)
        image_paths = []
        for img in submission.images:
            import hashlib

            digest = hashlib.sha256(img.data).hexdigest()
            ref = ImageRef(
                sha256=digest,
                mime_type=img.mime_type,
                byte_size=len(img.data),
                width=img.width,
                height=img.height,
                name=img.name,
            )
            path = store.resolve_path(ref)
            from urllib.request import pathname2url

            file_url = "file:///" + pathname2url(str(path)).lstrip("/")
            image_paths.append(file_url)
    except AssetError as exc:
        win._conversation.append_error(f"Couldn't load image preview: {exc}")
        win._conversation.append_user_message(_display_text(submission))
        return
    win._conversation.append_user_message_with_images(submission.text, image_paths)


def on_input_submitted(win, submission: str | UserSubmission) -> None:
    submission = _as_submission(submission)
    text = submission.text
    has_images = bool(submission.images)

    if win._compose_mode:
        win._toggle_compose()
    if text.lower() in ("exit", "quit", "q"):
        win.close()
        return
    if win._pending_ask is not None:
        if win._worker and win._worker.is_alive():
            if has_images:
                win._conversation.append_error(
                    "This question needs a text answer — images aren't supported here."
                )
                if hasattr(win, "_prompt"):
                    win._prompt.restore_draft(submission)
                return
            if win._pending_ask_container is not None:
                win._pending_ask_container.append(text)
            win._pending_ask.set()
            win._pending_ask = None
            win._pending_ask_container = None
            win._conversation.append_user_message(text)
            win._prompt.setDisabled(True)
            win._show_running()
            return
        # Nobody is left to read the answer: the ask_user call timed out
        # and its turn has since ended. Posting into the dead event would
        # show the running label without starting a worker — a hang.
        win._pending_ask = win._pending_ask_container = None
    # Inject-and-resume while paused
    if (
        win._worker and win._worker.is_alive()
        and win._current_loop_ref
        and not win._current_loop_ref[0]._pause_event.is_set()
    ):
        loop = win._current_loop_ref[0]
        _append_user_with_images(win, submission)
        win._prompt.setDisabled(True)
        win._show_running()
        win._right_sidebar.set_status("running")
        loop.inject_and_resume(submission)
        return
    if text.startswith("/"):
        if has_images:
            win._conversation.append_error(
                "Slash commands don't support image attachments."
            )
            if hasattr(win, "_prompt"):
                win._prompt.restore_draft(submission)
            return
        result = win._cmd_handler.handle(text)
        if result == "__EXIT__":
            win.close()
        elif result is not None:
            win._handle_special_command(result)
            if not result.startswith("__"):
                win._dispatch_agent(result)
        return
    win._dispatch_agent(submission)


def handle_special_command(win, result: str) -> None:
    if result == "__COMPACT__":
        win._do_compact()
    elif result.startswith("__WTF__"):
        win._do_wtf(result[7:] or None)
    elif result == "__COPY__":
        msgs = list(win._active_loop._messages) if win._active_loop else []
        win._copy_picker.show_messages(msgs)


def dispatch_agent(win, task: str | UserSubmission) -> None:
    if win._worker and win._worker.is_alive():
        win._conversation.append_info("Agent is already running — please wait.")
        if hasattr(win, "_prompt"):
            win._prompt.restore_draft(task if isinstance(task, UserSubmission) else _as_submission(task))
        return
    win._submission_seq = getattr(win, "_submission_seq", 0) + 1
    _append_user_with_images(win, _as_submission(task))
    win._prompt.setDisabled(True)
    win._show_running()
    win._current_loop_ref = []
    callbacks = win._bridge.build_callbacks(win._current_loop_ref)
    win._worker = threading.Thread(
        target=win._agent_work, args=(task, callbacks, win._current_loop_ref), daemon=True)
    win._worker.start()


def agent_work(win, task: str | UserSubmission, callbacks: object, loop_ref: list) -> None:
    t0 = time.monotonic()

    def log(msg: str) -> None:
        worker_log.info("[%.3fs] %s", time.monotonic() - t0, msg)

    win._invoke_on_main("_set_status_slot", "running"); log("worker started")
    try:
        tracker = win._active_loop.tracker if win._active_loop else None
        if win._restore_initial_messages is not None:
            initial, win._restore_initial_messages = win._restore_initial_messages, None
            initial_affect, win._restore_initial_affect = win._restore_initial_affect, None
        else:
            initial = win._active_loop._messages if win._active_loop else None
            initial_affect = None
        log(f"session captured (msgs={len(initial) if initial else 0})")
        loop = AgentLoop(
            win._config, callbacks, initial_messages=initial,
            initial_affect=initial_affect, _tracker=tracker,
        )
        log("AgentLoop constructed"); loop_ref.append(loop)
        win._active_loop = loop; win._cmd_handler.set_active_loop(loop)
        log("agent run started")
        loop.run(task); log("agent run completed")
    except AssetError as exc:
        log(f"EXCEPTION: {type(exc).__name__}: {exc}")
        worker_log.debug("".join(traceback.format_exception(exc)))
        win._bridge.error_occurred.emit(f"Image error: {exc}")
    except Exception as exc:
        log(f"EXCEPTION: {type(exc).__name__}: {exc}")
        worker_log.debug("".join(traceback.format_exception(exc)))
        win._bridge.error_occurred.emit(str(exc))
    finally:
        if loop_ref:
            try: loop_ref[0].finish()
            except Exception: pass
        win._invoke_on_main("_clear_pending_ask_slot")
        log("finally: idle"); win._invoke_on_main("_set_status_slot", "idle")
        win._invoke_on_main("_enable_input_slot")
