from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from pyside_gui.theme import with_theme
from pyside_gui.tool_labels import tool_kind, tool_label


_RESOURCES = Path(__file__).parent / "resources"
# Child of the worker logger, so page errors land in pyside_worker.log.
_page_log = logging.getLogger("dagi.pyside.worker.page")

REASONING_PREVIEW_MS = 120
REASONING_PREVIEW_CHARS = 4000

# The header agent._compaction puts on a summary; the card shows it as "gen N".
_SUMMARY_HEADER = re.compile(r"\[CONTEXT SUMMARY — [^\]]*\(generation (\d+)\)\]")


def _file_url(path: str | Path) -> str:
    return QUrl.fromLocalFile(str(path)).toString()


def _is_error_result(result: str) -> bool:
    head = result.lstrip()[:12].lower()
    return head.startswith(("error:", "[error"))


class _ConversationPage(QWebEnginePage):
    """Keeps the pane on the conversation: clicked links open externally."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            if url.scheme() in ("http", "https", "mailto", "file"):
                QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        # A failed render otherwise leaves no trace outside the page.
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            _page_log.warning("page error %s:%s %s", source, line, message)


class _PageBridge(QObject):
    """Calls from the page to Python, over QWebChannel (``window._dagi``)."""

    cancel_queued = Signal(str)
    rpa_repair = Signal(str)

    @Slot(str)
    def cancelQueued(self, queue_id: str) -> None:  # noqa: N802 - called from JS
        self.cancel_queued.emit(queue_id)

    @Slot(str)
    def rpaRepair(self, name: str) -> None:  # noqa: N802 - called from JS
        self.rpa_repair.emit(name)


class ConversationView(QWebEngineView):
    """QWebEngineView wrapper that loads the conversation template and
    exposes Python methods mapped to JS DOM-manipulation functions.

    Assistant text, reasoning and questions are passed as raw markdown; the
    page renders them with Vditor (Lute + KaTeX + highlight.js). Calls made
    before the page finishes loading are queued and replayed.
    """

    queued_cancel_requested = Signal(str)  # ✕ on a queued message
    rpa_repair_requested = Signal(str)  # Repair button on a halt card

    def __init__(self, verbose: bool = False) -> None:
        super().__init__()
        self._verbose = verbose
        self._ready = False
        self._pending: list[str] = []
        self._stream_reasoning = ""
        self._reasoning_dirty = False
        self._reasoning_timer = QTimer(self)
        self._reasoning_timer.setSingleShot(True)
        self._reasoning_timer.setInterval(REASONING_PREVIEW_MS)
        self._reasoning_timer.timeout.connect(self._push_reasoning_preview)
        self.setPage(_ConversationPage(self))
        self._page_bridge = _PageBridge(self)
        self._page_bridge.cancel_queued.connect(self.queued_cancel_requested)
        self._page_bridge.rpa_repair.connect(self.rpa_repair_requested)
        self._channel = QWebChannel(self)
        self._channel.registerObject("dagi", self._page_bridge)
        self.page().setWebChannel(self._channel)
        self.loadFinished.connect(self._on_load_finished)
        html = (_RESOURCES / "conversation.html").read_text(encoding="utf-8")
        self.setHtml(with_theme(html), QUrl.fromLocalFile(str(_RESOURCES) + "/"))

    def _on_load_finished(self, ok: bool) -> None:
        self._ready = ok
        if ok:
            pending, self._pending = self._pending, []
            for js in pending:
                self.page().runJavaScript(js)

    def _run_js(self, js: str) -> None:
        if self._ready:
            self.page().runJavaScript(js)
        else:
            self._pending.append(js)

    @staticmethod
    def _js_str(text: str) -> str:
        return json.dumps(text)

    def show_welcome(
        self, title: str, subtitle: str, image_path: str | Path | None = None,
    ) -> None:
        """Centered empty-chat screen; it disappears with the first message."""
        url = _file_url(image_path) if image_path else ""
        self._run_js(
            f"showWelcome({self._js_str(title)}, {self._js_str(subtitle)}, "
            f"{self._js_str(url)})"
        )

    def append_user_message(self, text: str) -> None:
        self._run_js(
            f"appendMessage('user', {self._js_str(text)})"
        )

    def append_user_message_with_images(
        self, text: str, image_paths: list[str]
    ) -> None:
        """Append a user message with text and local image thumbnails.

        ``image_paths`` should already be file:// URLs (or otherwise
        directly loadable by QWebEngine) — they are passed through JSON
        encoding and escaped again as text in JS before being placed in
        the DOM, so they are never interpreted as HTML.
        """
        paths_json = json.dumps(list(image_paths))
        self._run_js(
            f"appendUserMessageWithImages({self._js_str(text)}, {paths_json})"
        )

    def append_assistant(self, markdown: str) -> None:
        self._run_js(f"appendMarkdown({self._js_str(markdown)})")

    def append_tool_start(self, name: str, args: str) -> None:
        self._run_js(
            f"appendToolCall({self._js_str(tool_label(name, args))}, "
            f"{self._js_str(tool_kind(name))}, "
            f"{self._js_str(args)}, "
            f"{'true' if self._verbose else 'false'})"
        )

    def append_tool_end(self, name: str, result: str) -> None:
        failed = "true" if _is_error_result(result) else "false"
        self._run_js(f"updateToolResult({self._js_str(result)}, {failed})")

    def append_reasoning(self, markdown: str) -> None:
        self._run_js(f"appendReasoning({self._js_str(markdown)})")

    def append_compaction(
        self, kept: int, removed: int, summary: str, fallback: bool,
    ) -> None:
        """One collapsed line; the summary (markdown) shows when expanded."""
        m = _SUMMARY_HEADER.match(summary)
        status = f"gen {m.group(1)}" if m else ""
        body = summary[m.end():] if m else summary
        label = f"Context compacted — removed {removed} steps, kept {kept}"
        self._run_js(
            f"appendCompaction({self._js_str(label)}, {self._js_str(status)}, "
            f"{self._js_str(body.strip())}, {'true' if fallback else 'false'})"
        )

    def append_info(self, text: str) -> None:
        self._run_js(f"appendInfo({self._js_str(text)})")

    def append_error(self, text: str) -> None:
        self._run_js(f"appendError({self._js_str(text)})")

    def stream_start(self) -> None:
        self._reasoning_timer.stop()
        self._stream_reasoning = ""
        self._reasoning_dirty = False
        self._run_js("createStreamBubble()")

    def stream_delta(self, kind: str, chunk: str) -> None:
        if not chunk:
            return
        if kind == "reasoning":
            # Coalesced: one page call per REASONING_PREVIEW_MS, never one per
            # delta (re-sending the whole text per delta is quadratic and left
            # the page minutes behind on long reasoning).
            self._stream_reasoning += chunk
            self._reasoning_dirty = True
            if not self._reasoning_timer.isActive():
                self._reasoning_timer.start()
            return
        # The first answer delta ends the reasoning phase; tool-only turns
        # instead finalize it at stream_end. Later reasoning can refresh it.
        self._finish_reasoning()
        self._run_js(
            f"updateStreamBubble({self._js_str(kind)}, "
            f"{self._js_str(chunk)})"
        )

    def stream_end(self, markdown: str) -> None:
        self._finish_reasoning()
        self._run_js(f"finalizeStream({self._js_str(markdown)})")

    def append_queued_message(self, queue_id: str, text: str) -> None:
        """A message typed while the agent runs: a dim bubble pinned below the
        live turn, with a ✕ that emits ``queued_cancel_requested``."""
        self._run_js(f"appendQueuedMessage({self._js_str(queue_id)}, {self._js_str(text)})")

    def mark_queued_delivered(self, queue_id: str) -> None:
        """The model has the message: it joins the timeline as a normal bubble."""
        self._run_js(f"markQueuedDelivered({self._js_str(queue_id)})")

    def remove_queued_message(self, queue_id: str) -> None:
        self._run_js(f"removeQueuedMessage({self._js_str(queue_id)})")

    def interrupt_stream(self) -> None:
        """Freeze the streaming bubble (and its thinking block) as it stands."""
        self._finish_reasoning()
        self._run_js("interruptStream()")

    def _push_reasoning_preview(self) -> None:
        # The preview shows only its last few lines, so the tail is enough.
        tail = self._stream_reasoning[-REASONING_PREVIEW_CHARS:]
        self._run_js(f"updateReasoningPreview({self._js_str(tail)})")

    def _finish_reasoning(self) -> None:
        if self._reasoning_timer.isActive():
            # finalizeReasoning replaces the live block, so it must exist first.
            self._reasoning_timer.stop()
            self._push_reasoning_preview()
        if self._reasoning_dirty:
            self._run_js(f"finalizeReasoning({self._js_str(self._stream_reasoning)})")
            self._reasoning_dirty = False

    def clear(self) -> None:
        self._reasoning_timer.stop()
        self._stream_reasoning = ""
        self._reasoning_dirty = False
        self._run_js("clearConversation()")

    def scroll_to_bottom(self) -> None:
        self._run_js("scrollToBottom()")

    def append_emote(
        self, name: str, file_path: str, text: str, timestamp: str,
    ) -> None:
        self._run_js(
            f"appendEmoteCard({self._js_str(name)}, "
            f"{self._js_str(_file_url(file_path))}, "
            f"{self._js_str(text)}, "
            f"{self._js_str(timestamp)})"
        )

    def append_rpa_halt_card(self, info) -> None:
        """A halted rpa_run/rpa_patch (see ``pyside_gui.rpa_cards.HaltInfo``):
        Screenshot / Repair / Dismiss. ``info.screenshot`` is ``None`` when
        the run left no ``halt.png``."""
        screenshot_url = _file_url(info.screenshot) if info.screenshot else ""
        self._run_js(
            f"appendRpaHaltCard({self._js_str(info.name)}, "
            f"{self._js_str(info.step)}, "
            f"{self._js_str(info.reason)}, "
            f"{self._js_str(screenshot_url)})"
        )

    def append_subagent_event(
        self, subagent_type: str, line: str
    ) -> None:
        self._run_js(
            f"appendSubagentEvent({self._js_str(subagent_type)}, "
            f"{self._js_str(line)})"
        )

    def append_question(
        self,
        question: str,
        options: list[dict],
        timeout: float | None,
    ) -> None:
        self._run_js(
            f"appendQuestion({self._js_str(question)}, "
            f"{json.dumps(options)}, "
            f"{timeout if timeout else 'null'})"
        )
