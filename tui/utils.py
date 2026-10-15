from __future__ import annotations

import json
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
    "/write-plan": "Write an implementation plan", "/model": "Switch model  (/model <id>)",
    "/wtf": "Diagnose the active conversation  (/wtf [description])",
    "/show-pet": "Toggle desktop pet visibility",
    "/revise-history": "Undo last N steps  (/revise-history [N])",
}


def _colour(name: str) -> str:
    return _TOOL_COLOURS.get(name.lower(), "cyan")


def _truncate(text: str, n: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


def _breakdown(messages: list, tool_schemas: list | None = None) -> dict[str, int]:
    """Estimate token counts for the request's context buckets (chars // 4).

    'system' is the real system message as sent; sidebars split it against the file-based
    _system_breakdown() rows via _system_other(). 'reasoning' is the reasoning_content echoed
    back on assistant messages, and 'schemas' is the tool JSON sent alongside the messages —
    both are billed as prompt tokens. Compaction summaries (role=user, content starts with
    '[CONTEXT SUMMARY') are broken out into a separate 'summary' bucket so they don't
    inflate the user row."""
    _TOKENS_PER_IMAGE = 1024
    buckets: dict[str, int] = {
        "system": 0, "summary": 0, "user": 0, "assistant": 0, "reasoning": 0,
        "tools": 0, "schemas": 0,
    }
    if tool_schemas:
        buckets["schemas"] = len(json.dumps(tool_schemas, ensure_ascii=False)) // 4
    role_map = {"system": "system", "user": "user", "assistant": "assistant", "tool": "tools"}
    for m in messages:
        bucket = role_map.get(m.get("role", ""))
        if bucket is None:
            continue
        reasoning = m.get("reasoning_content") or ""
        if reasoning:
            buckets["reasoning"] += max(1, len(reasoning) // 4)
        content = m.get("content") or ""
        img_count = 0
        if isinstance(content, list):
            parts = []
            for b in content:
                if isinstance(b, dict):
                    if b.get("type") == "text":
                        parts.append(b.get("text", ""))
                    elif b.get("type") in ("dagi_image", "image_url"):
                        img_count += 1
                    else:
                        parts.append(b.get("text", "") if "text" in b else "")
                else:
                    parts.append(str(b))
            text = " ".join(parts)
        else:
            text = str(content)
        for tc in m.get("tool_calls") or []:
            if isinstance(tc, dict):
                text += tc.get("function", {}).get("arguments", "")
        toks = max(1, len(text) // 4) + img_count * _TOKENS_PER_IMAGE
        if bucket == "user" and text.startswith("[CONTEXT SUMMARY"):
            buckets["summary"] += toks
        else:
            buckets[bucket] += toks
    return buckets


def _system_breakdown(dagi_root: Path, project_path: Path) -> dict[str, int]:
    """Estimate token counts for the three system message components from source files.

    AGENTS.md is charged once. When dagi runs inside its own repo the two roots are the
    same directory, so counting both rows billed one file twice — into the sidebar Total
    and the context bar. The project row reports 0 in that case.
    """
    def _toks(path: Path) -> int:
        return max(1, len(path.read_text(encoding="utf-8")) // 4) if path.exists() else 0

    dagi_agents = dagi_root / "AGENTS.md"
    project_agents = project_path / "AGENTS.md"
    same_file = dagi_agents.resolve() == project_agents.resolve()

    return {
        "sys-prompt": (
            _toks(dagi_root / ".dagi" / "prompts" / "main" / "main_system.md")
            + _toks(dagi_root / "soul.md")
        ),
        "dagi/ag": _toks(dagi_agents),
        "proj/ag": 0 if same_file else _toks(project_agents),
    }


def _system_other(sys_parts: dict[str, int], buckets: dict[str, int]) -> int:
    """System-message tokens the file rows don't explain (tool/skill list, prompt sections).

    The real system message contains the files _system_breakdown() reads, so only the
    remainder is added on top; before the first request there is no real message yet.
    """
    return max(0, buckets.get("system", 0) - sum(sys_parts.values()))


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
