"""One-line, plain-language labels for tool calls in the conversation pane.

``tool_label("read", '{"path": "agent/loop.py"}')`` -> ``"Read agent/loop.py"``.
The harness derives the label from the tool name and its key argument; a
model-written description can override this later.
"""
from __future__ import annotations

import json

_MAX = 90

# tool name -> (verb, argument keys tried in order)
_LABELS: dict[str, tuple[str, tuple[str, ...]]] = {
    "read": ("Read", ("path",)),
    "write": ("Wrote", ("path",)),
    "edit": ("Edited", ("path",)),
    "edit_text": ("Edited", ("path",)),
    "show_file": ("Showed", ("path",)),
    "bash": ("Ran", ("command",)),
    "find": ("Found", ("pattern",)),
    "web_fetch": ("Fetched", ("url",)),
    "web_search": ("Searched the web for", ("query",)),
    "web_research": ("Researched", ("task",)),
    "explore_files": ("Explored", ("task",)),
    "skill": ("Loaded skill", ("skill", "name")),
    "run_skill_script": ("Ran skill script", ("script", "name")),
    "read_notepad": ("Read the notepad", ()),
    "emote": ("Posted", ("text",)),
    "switch_model": ("Switched model to", ("model", "model_id")),
    "create_plan": ("Created a plan", ()),
    "show_plan": ("Showed the plan", ()),
    "update_task_status": ("Updated task status", ()),
}

_FALLBACK_KEYS = ("path", "command", "query", "pattern", "url", "task", "name")


def _shorten(text: str, limit: int = _MAX) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _parse(args: str) -> dict:
    try:
        data = json.loads(args) if args else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _first(data: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


_KINDS = {
    "read": "file", "show_file": "file", "read_notepad": "file",
    "write": "edit", "edit": "edit", "edit_text": "edit", "copy": "edit",
    "bash": "terminal",
    "grep": "search", "find": "search", "explore_files": "search",
    "web_fetch": "globe", "web_search": "globe", "web_research": "globe",
}


def tool_kind(name: str) -> str:
    """Icon family for a tool: file, edit, terminal, search, globe or tool."""
    return _KINDS.get(name.rpartition(" ")[2], "tool")


def tool_label(name: str, args: str) -> str:
    """Label for a tool call. ``name`` may carry a subagent prefix
    (``"[explore] read"``); the prefix is kept in front of the label."""
    prefix, _, bare = name.rpartition(" ")
    data = _parse(args)
    if bare == "grep":
        pattern, path = data.get("pattern", ""), data.get("path", "")
        label = f'Searched "{_shorten(pattern, 50)}"' + (f" in {path}" if path else "")
    elif bare == "copy":
        label = f"Copied {data.get('src', '?')} → {data.get('dst', '?')}"
    elif bare in _LABELS:
        verb, keys = _LABELS[bare]
        target = _first(data, keys)
        label = f"{verb} {target}" if target else verb
    else:
        target = _first(data, _FALLBACK_KEYS)
        human = bare.replace("_", " ").capitalize()
        label = f"{human}: {target}" if target else human
    label = _shorten(label)
    return f"{prefix} {label}" if prefix else label
