from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import pathname2url

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView

from pyside_gui.markdown_renderer import render_markdown


_RESOURCES = Path(__file__).parent / "resources"


class ConversationView(QWebEngineView):
    """QWebEngineView wrapper that loads the conversation template and
    exposes Python methods mapped to JS DOM-manipulation functions."""

    def __init__(self, verbose: bool = False) -> None:
        super().__init__()
        self._verbose = verbose
        self._ready = False
        self._stream_reasoning = ""
        self._reasoning_dirty = False
        html_path = _RESOURCES / "conversation.html"
        self.load(QUrl.fromLocalFile(str(html_path)))
        self.loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok: bool) -> None:
        self._ready = ok

    def _run_js(self, js: str) -> None:
        if self._ready:
            self.page().runJavaScript(js)

    @staticmethod
    def _js_str(text: str) -> str:
        return json.dumps(text)

    def append_user_message(self, text: str) -> None:
        self._run_js(
            f"appendMessage('user', {self._js_str(text)})"
        )

    def append_assistant(self, html: str) -> None:
        self._run_js(f"appendMarkdown({self._js_str(html)})")

    def append_tool_start(self, name: str, args: str) -> None:
        self._run_js(
            f"appendToolCall({self._js_str(name)}, "
            f"{self._js_str(args)}, "
            f"{'true' if self._verbose else 'false'})"
        )

    def append_tool_end(self, name: str, result: str) -> None:
        self._run_js(
            f"updateToolResult({self._js_str(name)}, "
            f"{self._js_str(result)}, "
            f"{'true' if self._verbose else 'false'})"
        )

    def append_reasoning(self, text: str) -> None:
        html = render_markdown(text, allow_html=False)
        self._run_js(
            f"appendReasoning({self._js_str(html)})"
        )

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

    def stream_end(self, html: str) -> None:
        self._finish_reasoning()
        self._run_js(f"finalizeStream({self._js_str(html)})")

    def _finish_reasoning(self) -> None:
        if self._reasoning_dirty:
            html = render_markdown(self._stream_reasoning, allow_html=False)
            self._run_js(f"finalizeReasoning({self._js_str(html)})")
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
        file_url = "file:///" + pathname2url(file_path).lstrip("/")
        self._run_js(
            f"appendEmoteCard({self._js_str(name)}, "
            f"{self._js_str(file_url)}, "
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
        question_html = render_markdown(question)
        self._run_js(
            f"appendQuestion({self._js_str(question_html)}, "
            f"{json.dumps(options)}, "
            f"{timeout if timeout else 'null'})"
        )
