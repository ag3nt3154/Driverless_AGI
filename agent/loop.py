import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import openai

from agent.registry import ToolRegistry
from agent.session import SessionTracker, ToolCallRecord


# ── Compaction helpers ────────────────────────────────────────────────────────

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
    lines = []
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

DEFAULT_SYSTEM_PROMPT = """\
You are an expert coding assistant. You help users with coding tasks by reading files, executing commands, editing code, and writing new files.

Available tools:
- read: Read file contents
- bash: Execute bash commands
- edit: Make surgical edits to files
- write: Create or overwrite files

Guidelines:
- Use bash for file operations like ls, grep, find
- Use read to examine files before editing
- Use edit for precise changes (old text must match exactly)
- Use write only for new files or complete rewrites
- When summarizing your actions, output plain text directly - do NOT use cat or bash to display what you did
- Be concise in your responses
- Show file paths clearly when working with files

Documentation:
- Your own documentation (including custom model setup and theme creation) is at: {readme_path}
- Read it when users ask about features, configuration, or setup, and especially if the user asks you to add a custom model or provider, or create a custom theme.\
"""


@dataclass
class AgentConfig:
    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""  # always set by agent.config_loader.resolve_model_config
    max_iterations: int = 20
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    thread_id: str | None = None
    # Compaction (Pi-style)
    context_window: int = 128_000     # model's hard token limit
    reserve_tokens: int = 16_384      # headroom for summary response + next reply
    keep_recent_tokens: int = 20_000  # tail kept verbatim (token budget)


@dataclass
class AgentCallbacks:
    """Optional observer hooks for the agent loop. All default to no-ops so the
    CLI path pays zero cost. The UI wires these to queue events for live updates."""
    on_tool_start:     Callable[[str, str, str], None]          = field(default=lambda n, d, a: None)
    on_tool_end:       Callable[[str, str], None]               = field(default=lambda n, r: None)
    on_assistant_text: Callable[[str], None]                    = field(default=lambda t: None)
    on_token_update:   Callable[[int, int, float | None], None] = field(default=lambda i, o, c: None)
    on_iteration:      Callable[[int, int], None]               = field(default=lambda cur, mx: None)
    on_done:           Callable[[str], None]                    = field(default=lambda r: None)
    on_error:          Callable[[Exception], None]              = field(default=lambda e: None)
    on_api_call:       Callable[[list], None]                   = field(default=lambda msgs: None)
    on_reasoning:      Callable[[str], None]                    = field(default=lambda text: None)
    on_compaction:     Callable[[int, int], None]               = field(default=lambda kept, removed: None)


def _load_md(*filenames: str) -> str:
    parts = []
    for name in filenames:
        p = Path(name)
        if p.exists():
            parts.append(p.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts)


class AgentLoop:
    def __init__(
        self,
        config: AgentConfig,
        registry: ToolRegistry,
        callbacks: AgentCallbacks | None = None,
        initial_messages: list | None = None,
    ):
        self.callbacks = callbacks or AgentCallbacks()
        readme_path = (Path(__file__).parent.parent / "README.md").resolve()
        prompt = config.system_prompt.format(readme_path=readme_path)
        preamble = _load_md("soul.md", "agents.md")
        system = f"{preamble}\n\n---\n\n{prompt}" if preamble else prompt

        # Build labeled system-prompt sections for the UI expander
        self.system_parts: list[dict] = []
        for filename, label in [("soul.md", "SOUL.md"), ("agents.md", "AGENTS.md")]:
            p = Path(filename)
            if p.exists():
                self.system_parts.append({"label": label, "content": p.read_text(encoding="utf-8").strip()})
        self.system_parts.append({"label": "System Prompt", "content": prompt})

        if initial_messages:
            # multi-turn: continue from existing conversation history
            self._messages = list(initial_messages)
        else:
            self._messages = [{"role": "system", "content": system}]

        self.client = openai.OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.config = config
        self.registry = registry
        self.tracker = SessionTracker(model=config.model, thread_id=config.thread_id)
        self.tracker.record_system(system)

    def _compact_context(self) -> None:
        """Pi-style context compaction.

        Summarises the 'middle' of self._messages (everything older than the
        keep_recent_tokens tail) into a single cumulative summary message.
        Respects the OpenAI assistant/tool pairing invariant and supports
        progressive re-summarisation when a prior summary already exists.
        """
        msgs = self._messages
        head_end = 1  # index immediately after the system message (always [0])

        # ── B. Detect existing summary (progressive distillation) ─────────────
        prior_summary: str | None = None
        search_start = head_end
        if (
            len(msgs) > 1
            and msgs[1].get("role") == "user"
            and str(msgs[1].get("content", "")).startswith("[CONTEXT SUMMARY")
        ):
            prior_summary = str(msgs[1]["content"])
            search_start = 2  # skip the old summary when scanning safe cuts

        # ── C. Find safe cut points ────────────────────────────────────────────
        # A safe cut is between a closed tool result (or plain assistant turn)
        # and the next message. Never split an assistant/tool pair.
        safe_cuts: list[int] = []
        for i in range(search_start + 1, len(msgs)):
            prev = msgs[i - 1]
            if prev.get("role") == "tool":
                safe_cuts.append(i)
            elif prev.get("role") == "assistant" and not prev.get("tool_calls"):
                safe_cuts.append(i)

        if not safe_cuts:
            return  # no safe boundary yet; nothing to compact

        # ── D. Token-based tail boundary ──────────────────────────────────────
        accumulated = 0
        tail_start = len(msgs)
        for i in range(len(msgs) - 1, search_start - 1, -1):
            accumulated += _estimate_tokens(msgs[i])
            if accumulated >= self.config.keep_recent_tokens:
                tail_start = i
                break

        # ── E. Snap to nearest safe cut point at-or-before tail_start ─────────
        valid_cuts = [c for c in safe_cuts if c <= tail_start]
        if not valid_cuts:
            return  # entire history fits in the tail; nothing to compact
        tail_start = valid_cuts[-1]

        # ── F. Slice the middle to be summarised ──────────────────────────────
        middle = msgs[head_end:tail_start]
        if not middle:
            return

        # ── G. Build summarisation prompt ─────────────────────────────────────
        prior_section = (
            f"\n\n=== PRIOR SUMMARY (carry this forward) ===\n{prior_summary}"
            if prior_summary
            else ""
        )
        summarisation_messages = [
            {
                "role": "system",
                "content": (
                    "You are a precise technical summariser. "
                    "Compress the conversation history into a single cumulative summary. "
                    "Preserve every file path, tool call, result, decision, error, and "
                    "resolution. End with a '### Files Read/Modified' section listing "
                    "every file path mentioned. Output ONLY the summary — no preamble."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Produce a cumulative summary of the following conversation segment."
                    + prior_section
                    + "\n\n=== NEW CONVERSATION SEGMENT ===\n"
                    + _format_messages_for_summary(middle)
                    + "\n=== END ==="
                ),
            },
        ]

        summary_response = self.client.chat.completions.create(
            model=self.config.model,
            messages=summarisation_messages,
        )
        summary_text = summary_response.choices[0].message.content or "(no summary)"

        # ── H. Build replacement message (role=user avoids pairing invariant) ──
        summary_message = {
            "role": "user",
            "content": "[CONTEXT SUMMARY — prior conversation compacted]\n\n" + summary_text,
        }

        # ── I. Mutate in place ────────────────────────────────────────────────
        removed_count = len(middle)
        self._messages[head_end:tail_start] = [summary_message]

        # ── J. Notify observers ───────────────────────────────────────────────
        self.callbacks.on_compaction(len(self._messages), removed_count)

    def run(self, task: str) -> str:
        self._messages.append({"role": "user", "content": task})
        self.tracker.record_user(task)

        try:
            for iteration in range(self.config.max_iterations):
                self.callbacks.on_iteration(iteration + 1, self.config.max_iterations)

                self.callbacks.on_api_call(list(self._messages))
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=self._messages,
                    tools=self.registry.get_openai_tools_list(),
                    parallel_tool_calls=False,
                )
                message = response.choices[0].message
                _reasoning = getattr(message, "reasoning_content", None) or ""
                if _reasoning:
                    self.callbacks.on_reasoning(_reasoning)

                tool_records: list[ToolCallRecord] = []

                if not message.tool_calls:
                    # store assistant turn as dict to keep _messages serialisable
                    self._messages.append({"role": "assistant", "content": message.content})
                    result = message.content or ""
                    self.callbacks.on_assistant_text(result)
                    self.callbacks.on_token_update(
                        getattr(response.usage, "prompt_tokens", 0) or 0,
                        getattr(response.usage, "completion_tokens", 0) or 0,
                        getattr(response.usage, "cost", None),
                    )
                    self.tracker.record_assistant(message.content, response.usage, tool_records)
                    self.tracker.finish(raw_messages=self._messages)
                    self.callbacks.on_done(result)
                    return result

                # Interleave: each tool call is immediately followed by its result.
                # First call carries the assistant's text content; subsequent ones get None.
                if message.content:
                    self.callbacks.on_assistant_text(message.content)

                first = True
                for tc in message.tool_calls:
                    self._messages.append({
                        "role": "assistant",
                        "content": message.content if first else None,
                        "tool_calls": [{
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }],
                    })
                    first = False

                    tool_obj = self.registry._tools.get(tc.function.name)
                    description = tool_obj.description if tool_obj else tc.function.name
                    self.callbacks.on_tool_start(tc.function.name, description, tc.function.arguments)
                    self.tracker.record_tool_start(tc.function.name, description, tc.function.arguments)

                    result = self.registry.dispatch(
                        tc.function.name, json.loads(tc.function.arguments)
                    )
                    result_str = result if isinstance(result, str) else "__list__:" + json.dumps(result)
                    self.callbacks.on_tool_end(tc.function.name, result_str)
                    self.tracker.record_tool_end(tc.function.name, result_str)

                    tool_records.append(ToolCallRecord(
                        name=tc.function.name,
                        description=description,
                        input=tc.function.arguments,
                        result=result_str,
                    ))
                    self._messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result}
                    )

                self.tracker.record_assistant(message.content, response.usage, tool_records)
                self.callbacks.on_token_update(
                    getattr(response.usage, "prompt_tokens", 0) or 0,
                    getattr(response.usage, "completion_tokens", 0) or 0,
                    getattr(response.usage, "cost", None),
                )

                # ── Compaction trigger ────────────────────────────────────────
                _prompt_tok = getattr(response.usage, "prompt_tokens", 0) or 0
                if (
                    self.config.context_window > 0
                    and _prompt_tok > 0
                    and _prompt_tok > self.config.context_window - self.config.reserve_tokens
                ):
                    self._compact_context()
                # ─────────────────────────────────────────────────────────────

        except Exception as e:
            self.callbacks.on_error(e)
            raise

        # max iterations hit — ask for a summary
        summary_msg = "Max iterations reached. Summarize what you have done so far."
        self._messages.append({"role": "user", "content": summary_msg})
        self.tracker.record_user(summary_msg)
        self.callbacks.on_api_call(list(self._messages))
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=self._messages,
        )
        _final_msg = response.choices[0].message
        _final_reasoning = getattr(_final_msg, "reasoning_content", None) or ""
        if _final_reasoning:
            self.callbacks.on_reasoning(_final_reasoning)
        final = _final_msg.content or ""
        self.tracker.record_assistant(final, response.usage, [])
        self.tracker.finish(raw_messages=self._messages)
        self.callbacks.on_done(final)
        return final
