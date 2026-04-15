"""
agent/config_loader.py — single source of truth for dagi configuration.

config.yaml schema:
    default_model: <model_id>
    max_iterations: 20
    models:
      <model_id>:
        name: "Human-readable label"
        model: "provider/model-name"   # sent verbatim to the API
        api_url: "https://..."
        api_key_env: "ENV_VAR_NAME"    # pointer into .env — never the key itself
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Imported here to avoid a circular import — config_loader must not import AgentLoop.
# AgentConfig is a plain dataclass with no side effects.
from agent.loop import AgentConfig


@dataclass
class CliConfig:
    """CLI-specific settings loaded from the top-level `cli:` key in config.yaml."""
    threading: str = "threaded"  # "threaded" | "sync"
    verbose: bool = False

_CONFIG_PATH = Path("config.yaml")

_FALLBACK_MODEL_ID = "gpt-4o-openai"
_FALLBACK_ENTRY: dict = {
    "name": "GPT-4o (OpenAI)",
    "model": "gpt-4o",
    "api_url": "https://api.openai.com/v1",
    "api_key_env": "OPENAI_API_KEY",
}


def get_model_display_name(model_id: str | None = None) -> str:
    """Return the human-readable name for a model ID (falls back to the raw model string)."""
    raw = load_raw_config()
    catalog: dict = raw.get("models", {})
    chosen_id = model_id or raw.get("default_model") or _FALLBACK_MODEL_ID
    entry = catalog.get(chosen_id, _FALLBACK_ENTRY)
    return entry.get("name", chosen_id or "unknown")


def load_cli_config() -> CliConfig:
    """Return CLI settings from the `cli:` section of config.yaml, with safe defaults."""
    raw = load_raw_config()
    cli = raw.get("cli", {}) or {}
    return CliConfig(
        threading=cli.get("threading", "threaded"),
        verbose=bool(cli.get("verbose", False)),
    )


def load_raw_config() -> dict:
    """Return the full parsed config.yaml dict, or {} if the file is absent."""
    if not _CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}


def list_model_ids() -> list[str]:
    """Return the ordered list of model_id keys from the catalog."""
    return list(load_raw_config().get("models", {}).keys())


def resolve_model_config(model_id: str | None = None) -> AgentConfig:
    """
    Build an AgentConfig by looking up a model in the catalog.

    Resolution order:
      1. model_id argument (CLI --model or UI selectbox)
      2. default_model from config.yaml
      3. built-in fallback (gpt-4o-openai)

    Raises
    ------
    KeyError        if the resolved model_id is not in the catalog.
    EnvironmentError if the required API key env var is not set.
    """
    raw = load_raw_config()
    catalog: dict = raw.get("models", {})

    chosen_id = model_id or raw.get("default_model") or _FALLBACK_MODEL_ID

    if catalog and chosen_id not in catalog:
        available = ", ".join(catalog.keys())
        raise KeyError(
            f"Model '{chosen_id}' not found in config.yaml.\n"
            f"Available model IDs: {available}"
        )

    entry = catalog.get(chosen_id, _FALLBACK_ENTRY)
    api_key_env = entry.get("api_key_env", "OPENAI_API_KEY")
    api_key = os.environ.get(api_key_env, "")

    if not api_key:
        print(
            f"Warning: env var '{api_key_env}' is not set "
            f"(required for model '{chosen_id}'). "
            "Set it in .env.",
            file=sys.stderr,
        )

    # Per-model overrides take precedence (different models have different limits)
    context_window     = entry.get("context_window")      or raw.get("context_window",      128_000)
    reserve_tokens     = entry.get("reserve_tokens")      or raw.get("reserve_tokens",       16_384)
    keep_recent_tokens = entry.get("keep_recent_tokens")  or raw.get("keep_recent_tokens",   20_000)

    return AgentConfig(
        model=entry["model"],
        base_url=entry["api_url"],
        api_key=api_key,
        max_iterations=raw.get("max_iterations", 20),
        context_window=int(context_window),
        reserve_tokens=int(reserve_tokens),
        keep_recent_tokens=int(keep_recent_tokens),
    )


def save_config(default_model: str, max_iterations: int) -> None:
    """
    Persist default_model and max_iterations back to config.yaml.
    The models catalog is preserved exactly — it is never clobbered.
    """
    raw = load_raw_config()
    raw["default_model"] = default_model
    raw["max_iterations"] = max_iterations
    _CONFIG_PATH.write_text(
        yaml.dump(raw, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
