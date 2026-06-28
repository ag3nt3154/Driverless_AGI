"""Pure utilities for the Telegram bot interface."""
from __future__ import annotations


def chunk_message(text: str, limit: int = 4096) -> list[str]:
    """Split text into Telegram-safe chunks on paragraph boundaries."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Try splitting on double newline (paragraph), then single newline, then space
        cut = -1
        for sep in ("\n\n", "\n", " "):
            idx = remaining.rfind(sep, 0, limit)
            if idx > 0:
                cut = idx
                break

        if cut <= 0:
            cut = limit

        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    return [c for c in chunks if c.strip()]


def format_ask_options(question: str, options: list[dict]) -> str:
    """Format an ask_user question with numbered options for Telegram."""
    lines = [question, ""]
    for i, opt in enumerate(options, 1):
        label = opt.get("label", "")
        rec = " (recommended)" if opt.get("recommended") else ""
        lines.append(f"{i}. {label}{rec}")
    lines.append("")
    lines.append("Reply with the option number or type your answer.")
    return "\n".join(lines)
