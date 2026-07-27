"""
agent/config_loader.py — single source of truth for dagi configuration.

Two-layer config stack:
  1. {DAGI_ROOT}/.dagi/config.yaml          — base config (models catalog, defaults)
  2. {project_path}/.dagi/config.yaml        — project override (merged over base)

config.yaml schema:
    default_model: <model_id>
    models:
      <model_id>:
        name: "Human-readable label"
        model: "provider/model-name"   # sent verbatim to the API
        api_url: "https://..."
        api_key_env: "ENV_VAR_NAME"    # pointer into .env — never the key itself
        api_key: "sk-..."              # optional: inline key (overrides api_key_env)
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Imported here to avoid a circular import — config_loader must not import AgentLoop.
# AgentConfig is a plain dataclass with no side effects.
from agent.loop import AgentConfig
from agent import DAGI_ROOT


_CONFIG_PATH = DAGI_ROOT / ".dagi" / "config.yaml"

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


@dataclass
class TelegramConfig:
    """Telegram bot settings loaded from the `telegram:` key in .dagi/config.yaml."""
    bot_token: str = ""
    allowed_chat_ids: frozenset[int] = field(default_factory=frozenset)


def load_telegram_config() -> TelegramConfig:
    """Return Telegram settings from config.yaml, resolving bot token from env."""
    raw = load_raw_config()
    tg = raw.get("telegram", {}) or {}
    token_env = tg.get("bot_token_env", "TELEGRAM_BOT_TOKEN")
    token = os.environ.get(token_env, "")
    ids_env = tg.get("allowed_chat_ids_env", "TELEGRAM_ALLOWED_CHAT_IDS")
    ids_raw = os.environ.get(ids_env, "")
    allowed_chat_ids = frozenset(
        int(part) for part in ids_raw.split(",") if part.strip()
    )
    return TelegramConfig(bot_token=token, allowed_chat_ids=allowed_chat_ids)


def load_raw_config(config_path: Path | None = None) -> dict:
    """Return the full parsed config dict from {DAGI_ROOT}/.dagi/config.yaml,
    or {} if the file is absent.

    config_path overrides the default path (used by benchmark runners
    that need a separate config file).
    """
    path = config_path or _CONFIG_PATH
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def list_model_ids() -> list[str]:
    """Return the ordered list of model_id keys from the catalog."""
    return list(load_raw_config().get("models", {}).keys())


def _load_project_config(project_path: Path) -> dict | None:
    """Load project-level config from {project_path}/.dagi/config.yaml.

    Returns None if the file is absent. Raises ValueError on invalid YAML.
    """
    path = project_path / ".dagi" / "config.yaml"
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc


def _merge_configs(root_raw: dict, project_raw: dict) -> dict:
    """Merge project_raw over root_raw. Model catalogs are shallow-merged (project wins).
    All other top-level scalar fields: project value wins when key is present.
    """
    merged = dict(root_raw)
    root_models: dict = root_raw.get("models") or {}
    project_models: dict = project_raw.get("models") or {}
    merged["models"] = {**root_models, **project_models}
    for key, value in project_raw.items():
        if key != "models":
            merged[key] = value
    return merged


def _build_config_from_entry(entry: dict, raw: dict, model_id: str = "") -> AgentConfig:
    """Build an AgentConfig from a catalog entry dict and the top-level raw config."""
    direct_key = entry.get("api_key", "")
    if direct_key:
        api_key = direct_key
    else:
        api_key_env = entry.get("api_key_env", "OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env, "")

    context_window       = entry.get("context_window")        or raw.get("context_window",        128_000)
    reserve_tokens       = entry.get("reserve_tokens")        or raw.get("reserve_tokens",         16_384)
    keep_recent_tokens   = entry.get("keep_recent_tokens")    or raw.get("keep_recent_tokens",     20_000)
    null_response_retries = int(raw.get("null_response_retries", 3))
    max_continuations = int(raw.get("max_continuations", 10))
    api_error_retries = int(raw.get("api_error_retries", 3))
    thinking = entry.get("thinking") or raw.get("thinking", "none") or "none"
    cache_prompt = bool(entry.get("cache_prompt", raw.get("cache_prompt", False)))
    stream = bool(entry.get("stream", raw.get("stream", True)))

    raw_memory_root = raw.get("memory_root")
    memory_root = Path(raw_memory_root).expanduser() if raw_memory_root else None

    bash_backend = str(raw.get("bash_backend", "subprocess"))
    tools: list[str] | None = raw.get("tools") or None
    disabled_tools: list[str] | None = raw.get("disabled_tools") or None
    sandbox_mode = bool(raw.get("sandbox_mode", False))
    system_prompt_preamble = str(raw.get("system_prompt_preamble", "") or "")
    provider_order: list[str] | None = entry.get("provider_order") or None
    services = raw.get("services") or {}

    return AgentConfig(
        model=entry["model"],
        base_url=entry["api_url"],
        api_key=api_key,
        model_id=model_id,
        thinking=str(thinking).lower(),
        context_window=int(context_window),
        reserve_tokens=int(reserve_tokens),
        keep_recent_tokens=int(keep_recent_tokens),
        null_response_retries=null_response_retries,
        max_continuations=max_continuations,
        api_error_retries=api_error_retries,
        memory_root=memory_root,
        cache_prompt=cache_prompt,
        stream=stream,
        bash_backend=bash_backend,
        tools=tools,
        disabled_tools=disabled_tools,
        sandbox_mode=sandbox_mode,
        system_prompt_preamble=system_prompt_preamble,
        provider_order=provider_order,
        services=services,
    )


def resolve_model_config(
    model_id: str | None = None,
    config_path: Path | None = None,
    project_path: Path | None = None,
) -> AgentConfig:
    """
    Build an AgentConfig by looking up a model in the catalog.

    Resolution order:
      1. model_id argument (CLI --model or UI selectbox)
      2. default_model from {DAGI_ROOT}/.dagi/config.yaml
      3. built-in fallback (gpt-4o-openai)

    If project_path is given, {project_path}/.dagi/config.yaml is loaded and
    merged *over* the DAGI-root config. Project values win on all scalar fields;
    model catalog entries are shallow-merged (project entries add or fully
    replace root entries).

    config_path overrides the default config path (e.g. pass
    benchmarks/dagi_eval/config_dagi_eval.yaml for benchmark runs).

    If worker_model is set in the config and resolves to a known catalog entry,
    the returned config carries a worker_config field that sub-agents use instead
    of the primary model. Unrecognised worker_model values are silently ignored.

    Raises
    ------
    KeyError        if the resolved model_id is not in the catalog.
    EnvironmentError if the required API key env var is not set.
    ValueError       if project .dagi/config.yaml contains invalid YAML.
    """
    raw = load_raw_config(config_path=config_path)
    if project_path is not None:
        project_raw = _load_project_config(project_path)
        if project_raw:
            raw = _merge_configs(raw, project_raw)
    catalog: dict = raw.get("models", {})

    chosen_id = model_id or raw.get("default_model") or _FALLBACK_MODEL_ID

    if catalog and chosen_id not in catalog:
        available = ", ".join(catalog.keys())
        raise KeyError(
            f"Model '{chosen_id}' not found in .dagi/config.yaml.\n"
            f"Available model IDs: {available}"
        )

    entry = catalog.get(chosen_id, _FALLBACK_ENTRY)
    if not entry.get("api_key", ""):
        api_key_env = entry.get("api_key_env", "OPENAI_API_KEY")
        if not os.environ.get(api_key_env, ""):
            print(
                f"Warning: env var '{api_key_env}' is not set "
                f"(required for model '{chosen_id}'). "
                "Set it in .env or add api_key directly in config.yaml.",
                file=sys.stderr,
            )

    from dataclasses import replace

    cfg = _build_config_from_entry(entry, raw, model_id=chosen_id)
    cfg = replace(cfg, display_name=entry.get("name", chosen_id))
    if project_path is not None:
        cfg = replace(cfg, project_path=project_path)

    # Resolve optional worker model for sub-agents; silently fall back if unset/invalid.
    worker_id = raw.get("worker_model")
    worker_cfg: AgentConfig | None = None
    if worker_id and worker_id in catalog:
        worker_cfg = _build_config_from_entry(catalog[worker_id], raw, model_id=worker_id)
        worker_cfg = replace(worker_cfg, display_name=catalog[worker_id].get("name", worker_id))

    # Resolve optional advanced model for plan mode; silently fall back if unset/invalid.
    advanced_id = raw.get("advanced_model")
    advanced_cfg: AgentConfig | None = None
    if advanced_id and advanced_id in catalog:
        advanced_cfg = _build_config_from_entry(catalog[advanced_id], raw, model_id=advanced_id)
        advanced_cfg = replace(advanced_cfg, display_name=catalog[advanced_id].get("name", advanced_id))

    return replace(cfg, worker_config=worker_cfg, advanced_config=advanced_cfg)


def save_config(default_model: str) -> None:
    """Persist default_model back to {DAGI_ROOT}/.dagi/config.yaml.
    The models catalog is preserved exactly."""
    raw = load_raw_config()
    raw["default_model"] = default_model
    raw.pop("max_iterations", None)  # clean up legacy key if present
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        yaml.dump(raw, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
