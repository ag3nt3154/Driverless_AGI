from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from pyside_gui.theme import with_theme
from pyside_gui.tool_labels import tool_kind, tool_label


_RESOURCES = Path(__file__).parent / "resources"


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


class ConversationView(QWebEngineView):
    """QWebEngineView wrapper that loads the conversation template and
    exposes Python methods mapped to JS DOM-manipulation functions.

    Assistant text, reasoning and questions are passed as raw markdown; the
    page renders them with Vditor (Lute + KaTeX + highlight.js). Calls made
    before the page finishes loading are queued and replayed.
    """

    def __init__(self, verbose: bool = False) -> None:
        super().__init__()
        self._verbose = verbose
        self._ready = False
        self._pending: list[str] = []
        self._stream_reasoning = ""
        self._reasoning_dirty = False
        self.setPage(_ConversationPage(self))
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

    def append_info(self, text: str) -> None:
        self._run_js(f"appendInfo({self._js_str(text)})")

    def append_error(self, text: str) -> None:
        self._run_js(f"appendError({self._js_str(text)})")

    def stream_start(self) -> None:
        self._stream_reasoning = ""
        self._reasoning_dirty = False
        self._run_js("createStreamBubble()")

    def stream_delta(self, kind: str, chunk: str) -> None:
        if not chunk:
            return
        if kind == "reasoning":
            self._stream_reasoning += chunk
            self._reasoning_dirty = True
            self._run_js(f"updateReasoningPreview({self._js_str(self._stream_reasoning)})")
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

    def interrupt_stream(self) -> None:
        """Freeze the streaming bubble (and its thinking block) as it stands."""
        self._finish_reasoning()
        self._run_js("interruptStream()")

    def _finish_reasoning(self) -> None:
        if self._reasoning_dirty:
            self._run_js(f"finalizeReasoning({self._js_str(self._stream_reasoning)})")
            self._reasoning_dirty = False

    def clear(self) -> None:
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
