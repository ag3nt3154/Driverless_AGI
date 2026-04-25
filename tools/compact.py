"""
tools/compact.py — Context compaction tool (Pi-style progressive summarisation).

Not registered in the ToolRegistry (internal-only). Lives on AgentLoop as
``self.compact_tool`` and is invoked by:

  * The automatic token-threshold trigger inside AgentLoop.run()
  * The ``/compact`` CLI slash command
"""
from __future__ import annotations

from typing import Callable, NamedTuple, TYPE_CHECKING

import openai

from agent.base_tool import BaseTool
from agent.prompts import load_prompt

if TYPE_CHECKING:
    from agent.loop import AgentConfig

_COMPACT_SYSTEM = load_prompt("compact_system.md")
_COMPACT_USER = load_prompt("compact_user.md")


# ── Result type ───────────────────────────────────────────────────────────────

class CompactionResult(NamedTuple):
    """Returned by compact() so callers can track what happened."""
    did_compact: bool
    removed_count: int
    summary_input_tokens: int   # prompt tokens used by summarisation call
    summary_output_tokens: int  # completion tokens used by summarisation call
    summary_cost: float | None  # cost if reported by the API, else None


_NO_COMPACTION = CompactionResult(
    did_compact=False, removed_count=0,
    summary_input_tokens=0, summary_output_tokens=0, summary_cost=None,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _estimate_tokens(msg: dict) -> int:
    """Rough token estimate for a single message (1 token ≈ 4 chars)."""
    text = ""
    if msg.get("content"):
        text += str(msg["content"])
    for tc in msg.get("tool_calls") or []:
        text += str(tc.get("function", {}).get("arguments", ""))
    return max(len(text) // 4, 4)


def _format_messages_for_summary(messages: list[dict]) -> str:
    """Render a message slice as human-readable text for the summarizer."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        if role == "ASSISTANT":
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []
            if content:
                lines.append(f"[ASSISTANT]: {content}")
            for tc in tool_calls:
                fn = tc.get("function", {})
                lines.append(f"[TOOL CALL {fn.get('name', '')}]: {fn.get('arguments', '')}")
        elif role == "TOOL":
            lines.append(
                f"[TOOL RESULT tool_call_id={msg.get('tool_call_id', '')}]: {msg.get('content', '')}"
            )
        elif role == "USER":
            lines.append(f"[USER]: {msg.get('content', '')}")
    return "\n".join(lines)


# ── CompactTool ───────────────────────────────────────────────────────────────

class CompactTool(BaseTool):
    """Internal-only context compaction tool (not exposed to the LLM).

    Create it, then call :meth:`bind` once the loop's mutable state is ready.
    """

    name = "compact"
    description = "Compact conversation context into a cumulative summary."
    _parameters = {
        "type": "object",
        "properties": {
            "force": {
                "type": "boolean",
                "description": "Skip token-threshold check and always compact.",
            },
        },
        "required": [],
    }

    def __init__(self) -> None:
        self._messages: list[dict] | None = None
        self._config: AgentConfig | None = None
        self._client: openai.OpenAI | None = None
        self._on_compaction: Callable[[int, int], None] | None = None

    def bind(
        self,
        messages: list[dict],
        config: "AgentConfig",
        client: openai.OpenAI,
        on_compaction: Callable[[int, int], None] | None = None,
    ) -> None:
        """Late-bind to mutable loop state. Must be called before compact()."""
        self._messages = messages
        self._config = config
        self._client = client
        self._on_compaction = on_compaction

    # ── BaseTool interface (human-readable output) ────────────────────────

    def run(self, force: bool = False) -> str:
        result = self.compact(force=force)
        if result.did_compact:
            return (
                f"Context compacted — removed {result.removed_count} messages. "
                f"Summarisation cost: {result.summary_input_tokens} in / "
                f"{result.summary_output_tokens} out tokens."
            )
        return "Nothing to compact."

    # ── Programmatic interface ────────────────────────────────────────────

    def compact(self, *, force: bool = False) -> CompactionResult:
        """Pi-style context compaction.

        Summarises the 'middle' of the conversation (everything older than
        the ``keep_recent_tokens`` tail) into a single cumulative summary
        message. Respects the OpenAI assistant/tool pairing invariant and
        supports progressive re-summarisation.

        When *force* is True the token-threshold check is skipped (used by
        the ``/compact`` slash command).

        Returns a :class:`CompactionResult`. Messages list is mutated in
        place.
        """
        if self._messages is None or self._config is None or self._client is None:
            raise RuntimeError("CompactTool.bind() must be called before compact()")

        msgs = self._messages
        config = self._config
        head_end = 1  # index immediately after the system message (always [0])

        # ── Detect existing summary (progressive distillation) ────────────
        prior_summary: str | None = None
        search_start = head_end
        if (
            len(msgs) > 1
            and msgs[1].get("role") == "user"
            and str(msgs[1].get("content", "")).startswith("[CONTEXT SUMMARY")
        ):
            prior_summary = str(msgs[1]["content"])
            search_start = 2  # skip the old summary when scanning safe cuts

        # ── Find safe cut points ──────────────────────────────────────────
        safe_cuts: list[int] = []
        for i in range(search_start + 1, len(msgs)):
            prev = msgs[i - 1]
            if prev.get("role") == "tool":
                safe_cuts.append(i)
            elif prev.get("role") == "assistant" and not prev.get("tool_calls"):
                safe_cuts.append(i)

        if not safe_cuts:
            return _NO_COMPACTION

        # ── Token-based tail boundary ─────────────────────────────────────
        accumulated = 0
        tail_start = len(msgs)
        for i in range(len(msgs) - 1, search_start - 1, -1):
            accumulated += _estimate_tokens(msgs[i])
            if accumulated >= config.keep_recent_tokens:
                tail_start = i
                break

        # ── Snap to nearest safe cut point at-or-before tail_start ────────
        valid_cuts = [c for c in safe_cuts if c <= tail_start]
        if not valid_cuts:
            if not force:
                return _NO_COMPACTION
            # force mode: use last safe cut even if inside the tail
            valid_cuts = safe_cuts
        tail_start = valid_cuts[-1]

        # ── Slice the middle to be summarised ─────────────────────────────
        middle = msgs[head_end:tail_start]
        if not middle:
            return _NO_COMPACTION

        # ── Build summarisation prompt ────────────────────────────────────
        prior_section = (
            f"\n\n=== PRIOR SUMMARY (carry this forward) ===\n{prior_summary}"
            if prior_summary
            else ""
        )
        summarisation_messages = [
            {"role": "system", "content": _COMPACT_SYSTEM},
            {
                "role": "user",
                "content": _COMPACT_USER.format(
                    prior_section=prior_section,
                    conversation=_format_messages_for_summary(middle),
                ),
            },
        ]

        summary_response = self._client.chat.completions.create(
            model=config.model,
            messages=summarisation_messages,
        )
        summary_text = summary_response.choices[0].message.content or "(no summary)"

        # ── Token usage from the summarisation call ───────────────────────
        su = summary_response.usage
        sum_in = getattr(su, "prompt_tokens", 0) or 0
        sum_out = getattr(su, "completion_tokens", 0) or 0
        sum_cost = getattr(su, "cost", None)

        # ── Build replacement message (role=user avoids pairing invariant) ─
        summary_message = {
            "role": "user",
            "content": "[CONTEXT SUMMARY — prior conversation compacted]\n\n" + summary_text,
        }

        # ── Mutate in place ───────────────────────────────────────────────
        removed_count = len(middle)
        msgs[head_end:tail_start] = [summary_message]

        # ── Notify observers ──────────────────────────────────────────────
        if self._on_compaction:
            self._on_compaction(len(msgs), removed_count)

        return CompactionResult(
            did_compact=True,
            removed_count=removed_count,
            summary_input_tokens=sum_in,
            summary_output_tokens=sum_out,
            summary_cost=sum_cost,
        )
