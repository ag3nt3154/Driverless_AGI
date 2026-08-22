from __future__ import annotations

from pathlib import Path

# Pure parsing is in agent/history.py (no Textual imports, shared with the GUI sidecar)
from agent.history import (
    build_copyable_messages as _build_copy_items_data,
    build_turn_list,
    load_affect_restore,
    load_raw_messages,
    load_sessions,
)

__all__ = ["load_sessions", "load_raw_messages", "load_affect_restore", "build_turn_list"]


def _build_copy_items(messages: list[dict]) -> list[dict]:
    """Thin alias kept for backward-compat with internal TUI callers."""
    return _build_copy_items_data(messages)


# ---------------------------------------------------------------------------
# Textual UI — HistoryScreen / CopyScreen
# ---------------------------------------------------------------------------

from textual.app import ComposeResult
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, OptionList
from textual.widgets.option_list import Option


def _build_copy_items(messages: list[dict]) -> list[dict]:
    """Extract copyable user/assistant messages from a raw_messages list.

    Returns list of {label, content} dicts, oldest-first.
    Skips system messages, tool messages, tool-call-only assistant turns,
    and compaction summaries.
    """
    items = []
    for msg in messages:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            text = " ".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        elif content:
            text = str(content)
        else:
            continue
        text = text.strip()
        if not text or text.startswith("[CONTEXT SUMMARY"):
            continue
        role_label = "You" if role == "user" else "DAGI"
        preview = text[:72].replace("\n", " ")
        if len(text) > 72:
            preview += "…"
        items.append({"label": f"[{role_label}]  {preview}", "content": text})
    return items


class CopyScreen(Screen):
    """Full-screen message picker for copying conversation text to clipboard.

    Takes the current session's raw messages and presents user + assistant
    turns in an OptionList. Posts CopyScreen.MessageCopied on selection.
    """

    BINDINGS = [("escape", "dismiss_screen", "Cancel")]

    class MessageCopied(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Dismissed(Message):
        pass

    def __init__(self, messages: list[dict]) -> None:
        super().__init__()
        self._items = _build_copy_items(messages)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Select message to copy  (↑/↓  Enter  Esc=cancel)", id="copy-label")
        yield OptionList(id="copy-list")
        yield Footer()

    def on_mount(self) -> None:
        opt_list = self.query_one("#copy-list", OptionList)
        if not self._items:
            opt_list.add_option(Option("(no messages in current session)", disabled=True))
        else:
            for i, item in enumerate(self._items):
                opt_list.add_option(Option(item["label"], id=f"msg_{i}"))
        opt_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        option_id = event.option.id or ""
        if option_id.startswith("msg_"):
            idx = int(option_id[4:])
            self.post_message(self.MessageCopied(self._items[idx]["content"]))

    def action_dismiss_screen(self) -> None:
        self.post_message(self.Dismissed())


class HistoryScreen(Screen):
    """Full-screen two-step session picker.

    Step 1: Lists the most recent sessions from logs_dir.
    Step 2: Lists user turns within the selected session.

    Posts SessionSelected or Dismissed to the app.
    """

    BINDINGS = [
        ("escape", "dismiss_screen", "Back / Cancel"),
    ]

    class SessionSelected(Message):
        """Emitted when the user picks a turn to resume from."""

        def __init__(self, path: Path, turn_index: int) -> None:
            super().__init__()
            self.path = path
            self.turn_index = turn_index

    class Dismissed(Message):
        """Emitted when the user presses Escape to cancel."""

    def __init__(self, logs_dir: Path, max_sessions: int = 20) -> None:
        super().__init__()
        self._logs_dir = logs_dir
        self._max_sessions = max_sessions
        self._sessions: list[dict] = []
        self._selected_session: dict | None = None
        self._selected_raw: list[dict] | None = None  # cached raw_messages for step 2

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Session History — select a session (↑/↓, Enter)", id="hist-label")
        yield OptionList(id="hist-list")
        yield Footer()

    def on_mount(self) -> None:
        self._load_sessions()

    def _load_sessions(self) -> None:
        self._sessions = load_sessions(self._logs_dir, self._max_sessions)
        opt_list = self.query_one("#hist-list", OptionList)
        opt_list.clear_options()
        if not self._sessions:
            opt_list.add_option(Option("(no sessions found)", disabled=True))
            return
        for sess in self._sessions:
            ts = sess["started_at"][:16].replace("T", " ") if sess["started_at"] else "?"
            label = f"{ts}  {sess['title']}"
            opt_list.add_option(Option(label))
        opt_list.focus()

    def _load_turns(self, session: dict) -> None:
        raw = load_raw_messages(session["path"])
        self._selected_raw = raw  # cache to avoid re-reading in option_selected handler
        opt_list = self.query_one("#hist-list", OptionList)
        opt_list.clear_options()
        lbl = self.query_one("#hist-label", Label)
        lbl.update("Select turn to resume from (most recent at bottom):")
        if not raw:
            opt_list.add_option(
                Option(
                    "(session has no raw_messages — cannot restore)",
                    disabled=True,
                )
            )
            opt_list.add_option(Option("↩ Press Escape to go back", disabled=True))
            opt_list.focus()
            return
        turns = build_turn_list(raw)
        if not turns:
            opt_list.add_option(Option("(no user turns found)", disabled=True))
            opt_list.focus()
            return
        # Show "resume from end" at top as a convenience option
        opt_list.add_option(Option("► Resume from latest (full context)", id="turn_end"))
        for t in turns:
            opt_list.add_option(
                Option(f"  [{t['index']:3d}] {t['label']}", id=f"turn_{t['index']}")
            )
        opt_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if self._selected_session is None:
            # Step 1 -> Step 2: user selected a session
            idx = event.option_index
            if idx >= len(self._sessions):
                return
            self._selected_session = self._sessions[idx]
            self._load_turns(self._selected_session)
        else:
            # Step 2: user selected a turn
            option_id = event.option.id or ""
            sess = self._selected_session
            raw = self._selected_raw  # use cached value from _load_turns
            total = len(raw) if raw else 0
            if option_id == "turn_end":
                turn_index = total
            elif option_id.startswith("turn_"):
                try:
                    turn_index = int(option_id[5:])
                except ValueError:
                    turn_index = total
            else:
                turn_index = total
            self.post_message(self.SessionSelected(sess["path"], turn_index))

    def action_dismiss_screen(self) -> None:
        if self._selected_session is not None:
            # In step 2 — go back to step 1
            self._selected_session = None
            self._selected_raw = None
            lbl = self.query_one("#hist-label", Label)
            lbl.update("Session History — select a session (↑/↓, Enter)")
            self._load_sessions()
        else:
            self.post_message(self.Dismissed())
