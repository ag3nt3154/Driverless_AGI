"""agent/_loop_config.py — dataclasses for the agent loop.

Extracted verbatim from agent/loop.py so the loop orchestrator stays under the
500-line cap. Only agent/loop.py imports from this module; external importers
keep using `from agent.loop import AgentConfig, ...` (re-exported there).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent.expression import ExpressionSnapshot
from agent.process_state import ProcessSnapshot


@dataclass
class CompactionResult:
    did_compact: bool
    generation: int = 0
    summary_content: str | None = None
    removed_count: int = 0


_NO_COMPACTION = CompactionResult(did_compact=False)


@dataclass
class AgentConfig:
    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""  # always set by agent.config_loader.resolve_model_config
    system_prompt: str = ""  # loaded from files at AgentLoop init time if empty
    thread_id: str | None = None
    thinking: str = "none"  # "none" | "low" | "medium" | "high"
    # Compaction (Pi-style)
    context_window: int = 128_000     # model's hard token limit
    reserve_tokens: int = 16_384      # headroom for summary response + next reply
    keep_recent_tokens: int = 20_000  # tail kept verbatim (token budget)
    # Project scope
    project_path: Path = field(default_factory=lambda: Path(".").resolve())
    # Memory root — absolute path to dagi-memory directory.
    # None means "resolve at loop init time to project_path / dagi-memory".
    memory_root: Path | None = None
    # Plan mode
    plan_mode: bool = False
    plan_file: str | None = None  # absolute path to the active plan document
    plan_mode_initiated_by: str = "user"  # "user" | "dagi"
    # Worker model (cheaper LLM for sub-agents); None = use this config as-is
    worker_config: AgentConfig | None = field(default=None)
    # Advanced model (dedicated LLM for plan mode); None = use this config as-is
    advanced_config: AgentConfig | None = field(default=None)
    # Active plan file persisted in system prompt after plan mode exits
    active_plan_file: str | None = None
    # Branch the user was on before entering plan mode — used for checkout-back at task end
    previous_branch: str | None = None
    # Human-readable label from the config catalog (e.g. "GPT-4o (OpenAI)")
    display_name: str = ""
    # Resolved model ID from the catalog (e.g. "gpt-4o-openai"). Set by resolve_model_config.
    # Used by the TUI to update sidebar state when /wd triggers a project switch.
    model_id: str = ""
    # Continuation: max times the harness injects "continue" before giving up
    max_continuations: int = 10
    # Ghost-response retries: how many times to silently retry an API call that
    # returns content=None with zero token usage before surfacing an error.
    null_response_retries: int = 3
    # Transient API error retries: how many times to retry on 429/5xx/connection
    # errors before propagating the exception. Independent of null_response_retries.
    api_error_retries: int = 3
    # Send cache_prompt: true in extra_body — enables prompt caching on OpenRouter.
    cache_prompt: bool = False
    # Streaming: consume the API response as a chunk stream, firing per-delta
    # callbacks. Dataclass default is False so direct AgentConfig() construction
    # (tests, benchmarks) keeps the blocking path; config_loader defaults the
    # config-file value to True, so all real entry points stream unless
    # .dagi/config.yaml sets `stream: false` (globally or per-model).
    stream: bool = False
    # bash_backend: previously controlled whether BashTool was replaced by an injected tool.
    # Now a no-op for tool registration — both BashTool and any injected tool are always
    # registered. Kept for config file backwards compatibility.
    bash_backend: str = "subprocess"
    # Accessible tools: None = all tools available; list = only named tools registered.
    tools: list[str] | None = None
    # Disabled tools: tools to remove from the registry even when `tools` is None.
    disabled_tools: list[str] | None = None
    # Sandbox mode: when True, file tools have no path restrictions (allowed_roots=None).
    sandbox_mode: bool = False
    # Benchmark/sandbox environment preamble injected at the TOP of the system prompt.
    system_prompt_preamble: str = ""
    # OpenRouter provider routing: ordered list of provider slugs to try in sequence
    # (e.g. ["Anthropic", "Together"]). None means use OpenRouter's default load balancing.
    # Sent as extra_body["provider"]["order"] — ignored by non-OpenRouter endpoints.
    provider_order: list[str] | None = None
    # Scheduler: override the ask_user timeout (seconds). None = use default (300s).
    # Set to 60 by the scheduler runner for fully autonomous execution.
    ask_user_timeout: int | None = None
    # External service URLs (e.g. {"doc_converter": "http://localhost:8100"}).
    # Loaded from the `services` block in .dagi/config.yaml.
    services: dict[str, str] = field(default_factory=dict)
    expression_interval: float = 1.0
    # Active Python environment detected at startup (e.g. "conda:dagi" or "venv:/path")
    # Set by config_loader._detect_python_env()
    python_env: str = ""


@dataclass
class AgentCallbacks:
    """Optional observer hooks for the agent loop. All default to no-ops so the
    CLI path pays zero cost. The UI wires these to queue events for live updates."""
    on_tool_start:     Callable[[str, str, str], None]          = field(default=lambda n, d, a: None)
    on_tool_end:       Callable[[str, str], None]               = field(default=lambda n, r: None)
    on_assistant_text: Callable[[str], None]                    = field(default=lambda t: None)
    on_token_update:   Callable[[int, int, float | None, int, int], None] = field(default=lambda i, o, c, t, ca=0: None)
    on_iteration:      Callable[[int], None]                    = field(default=lambda cur: None)
    on_done:           Callable[[str], None]                    = field(default=lambda r: None)
    on_handoff:        Callable[[], None]                       = field(default=lambda: None)
    on_error:          Callable[[Exception], None]              = field(default=lambda e: None)
    on_api_call:       Callable[[list], None]                   = field(default=lambda msgs: None)
    on_reasoning:      Callable[[str], None]                    = field(default=lambda text: None)
    on_compaction:     Callable[[int, int], None]               = field(default=lambda kept, removed: None)
    on_model_switch:   Callable[[str, str], None]               = field(default=lambda f, t: None)
    on_expression_changed: Callable[[ExpressionSnapshot], None] = field(
        default=lambda snapshot: None
    )
    on_process_state_changed: Callable[[ProcessSnapshot], None] = field(
        default=lambda snapshot: None
    )
    on_ask_user:       Callable[[str, list, "float | None"], str] = field(
        default=lambda question, options, timeout: next(
            (o["label"] for o in options if o.get("recommended")),
            options[0]["label"] if options else "",
        )
    )
    # Factory for subagent stdout relay: takes subagent_type, returns per-event callback.
    # None in headless / CLI mode — subagent output is not relayed.
    on_subagent_event_factory: Callable[[str], Callable[[str], None]] | None = None
    # Pause-on-error: when True, transient API errors that exhaust retries pause the loop
    # instead of raising. The TUI sets this True and wires on_pause to re-enable input.
    # CLI and subagents leave it False so existing raise behaviour is fully preserved.
    on_pause:       Callable[[], None] = field(default=lambda: None)
    supports_pause: bool               = False
    # Fired when the harness injects a "continue" prompt because the response had no exit flag.
    # Args: (current_count, max_continuations)
    on_continue_injected: Callable[[int, int], None] = field(default=lambda cur, mx: None)
    # Fired when a plan is rendered for interactive review (ShowPlanTool, interactive mode only).
    on_plan_shown: Callable[[], None] = field(default=lambda: None)
    # Streaming (config.stream=True only). on_stream_start fires before the first
    # chunk, on_stream_end always fires when consumption stops (even on error).
    # Deltas carry the raw incremental string for that chunk. The existing
    # on_assistant_text / on_reasoning still fire once afterward with full text.
    on_stream_start:         Callable[[], None]    = field(default=lambda: None)
    on_stream_end:           Callable[[], None]    = field(default=lambda: None)
    on_assistant_text_delta: Callable[[str], None] = field(default=lambda t: None)
    on_reasoning_delta:      Callable[[str], None] = field(default=lambda t: None)
