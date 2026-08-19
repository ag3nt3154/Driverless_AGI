from __future__ import annotations

from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

_TOOL_COLOURS = {
    "bash": "yellow", "read": "blue", "write": "green",
    "edit": "magenta", "grep": "cyan", "find": "cyan",
    "skill": "bright_magenta", "cli_subagent": "bright_blue",
}
_SLASH_HELP = {
    "/help": "Show this list", "/exit": "Exit",
    "/clear": "Clear conversation context", "/wd": "Show or set working directory",
    "/compact": "Force-compact context", "/tools": "List tools",
    "/skills": "List skills", "/workflows": "List workflows",
    "/init": "Initialise .dagi/ scaffold", "/hist": "Show recent sessions",
    "/copy": "Copy last assistant response to clipboard",
    "/plan": "Enter plan mode", "/model": "Switch model  (/model <id>)",
    "/wtf": "Diagnose the active conversation  (/wtf [description])",
}


def _colour(name: str) -> str:
    return _TOOL_COLOURS.get(name.lower(), "cyan")


def _truncate(text: str, n: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


def _breakdown(messages: list) -> dict[str, int]:
    """Estimate token counts for user/assistant/tools/summary buckets (chars // 4).
    System messages are excluded — accounted for by _system_breakdown() from source files.
    Compaction summaries (role=user, content starts with '[CONTEXT SUMMARY') are broken out
    into a separate 'summary' bucket so they don't inflate the user row."""
    buckets: dict[str, int] = {"summary": 0, "user": 0, "assistant": 0, "tools": 0}
    role_map = {"user": "user", "assistant": "assistant", "tool": "tools"}
    for m in messages:
        bucket = role_map.get(m.get("role", ""))
        if bucket is None:
            continue
        content = m.get("content") or ""
        if isinstance(content, list):
            text = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        else:
            text = str(content)
        for tc in m.get("tool_calls") or []:
            if isinstance(tc, dict):
                text += tc.get("function", {}).get("arguments", "")
        toks = max(1, len(text) // 4)
        if bucket == "user" and text.startswith("[CONTEXT SUMMARY"):
            buckets["summary"] += toks
        else:
            buckets[bucket] += toks
    return buckets


def _system_breakdown(dagi_root: Path, project_path: Path) -> dict[str, int]:
    """Estimate token counts for the three system message components from source files."""
    def _toks(path: Path) -> int:
        return max(1, len(path.read_text(encoding="utf-8")) // 4) if path.exists() else 0

    return {
        "sys-prompt": (
            _toks(dagi_root / ".dagi" / "prompts" / "main" / "main_system.md")
            + _toks(dagi_root / "soul.md")
        ),
        "dagi/ag": _toks(dagi_root / "AGENTS.md"),
        "proj/ag": _toks(project_path / "AGENTS.md"),
    }


# ── Stats ─────────────────────────────────────────────────────────────────────

class _Stats:
    def __init__(self) -> None:
        self.input_tok = 0
        self.output_tok = 0
        self.thinking_tok = 0
        self.cached_tok = 0
        self.cost: float | None = None
        self.tool_counts: dict[str, int] = {}

    def update_tokens(
        self, inp: int, out: int, cost: float | None, thinking: int = 0, cached: int = 0
    ) -> None:
        self.input_tok += inp
        self.output_tok += out
        self.thinking_tok += thinking
        self.cached_tok += cached
        if cost is not None:
            self.cost = (self.cost or 0.0) + cost

    def record_tool(self, name: str) -> None:
        self.tool_counts[name] = self.tool_counts.get(name, 0) + 1
