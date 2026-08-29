from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView


_RESOURCES = Path(__file__).parent / "resources"


class ConversationView(QWebEngineView):
    """QWebEngineView wrapper that loads the conversation template and
    exposes Python methods mapped to JS DOM-manipulation functions."""

    def __init__(self, verbose: bool = False) -> None:
        super().__init__()
        self._verbose = verbose
        self._ready = False
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
        self._run_js(
            f"appendReasoning({self._js_str(text)})"
        )

    def append_info(self, text: str) -> None:
        self._run_js(f"appendInfo({self._js_str(text)})")

    def append_error(self, text: str) -> None:
        self._run_js(f"appendError({self._js_str(text)})")

    def stream_start(self) -> None:
        self._run_js("createStreamBubble()")

    def stream_delta(self, kind: str, chunk: str) -> None:
        self._run_js(
            f"updateStreamBubble({self._js_str(kind)}, "
            f"{self._js_str(chunk)})"
        )

    def stream_end(self, html: str) -> None:
        self._run_js(f"finalizeStream({self._js_str(html)})")

    def clear(self) -> None:
        self._run_js("clearConversation()")

    def scroll_to_bottom(self) -> None:
        self._run_js("scrollToBottom()")

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
            f"{self._js_str(json.dumps(options))}, "
            f"{timeout if timeout else 'null'})"
        )
