#!/usr/bin/env python3
"""
Prompt Optimization CLI.

Usage:
    conda run --no-capture-output -n dagi python prompt_opt/run.py
    conda run --no-capture-output -n dagi python prompt_opt/run.py --iterations 5 --verbose
    conda run --no-capture-output -n dagi python prompt_opt/run.py --mode agent --iterations 3

All paths in config.yaml are relative to the config file's directory (prompt_opt/).
API keys are read from environment variables (set them in .env at the project root).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv


def _resolve_api_key(api_key_env: str, model_label: str) -> str:
    key = os.environ.get(api_key_env, "")
    if not key:
        print(
            f"Warning: env var '{api_key_env}' is not set (required for {model_label}). "
            "Set it in .env at the project root.",
            file=sys.stderr,
        )
    return key


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        sys.exit(f"Config file not found: {config_path}")
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def build_eval_client(cfg: dict, overrides: dict):
    from prompt_opt.llm_client import LLMClient, LLMClientConfig

    model_cfg = dict(cfg.get("eval_model", {}))
    if overrides.get("eval_model"):
        model_cfg["model"] = overrides["eval_model"]

    api_key = _resolve_api_key(model_cfg.get("api_key_env", "OPENAI_API_KEY"), "eval_model")
    return LLMClient(LLMClientConfig(
        model=model_cfg["model"],
        api_key=api_key,
        base_url=model_cfg.get("api_url", "https://api.openai.com/v1"),
        temperature=float(model_cfg.get("temperature", 0.0)),
        max_retries=int(cfg.get("max_retries", 3)),
    ))


def build_optimizer_llm_cfg(cfg: dict, overrides: dict):
    from prompt_opt.llm_client import LLMClientConfig

    opt_cfg = dict(cfg.get("optimizer", {}))
    if overrides.get("optimizer_model"):
        opt_cfg["model"] = overrides["optimizer_model"]

    api_key = _resolve_api_key(opt_cfg.get("api_key_env", "OPENAI_API_KEY"), "optimizer")
    return LLMClientConfig(
        model=opt_cfg.get("model", "gpt-4o"),
        api_key=api_key,
        base_url=opt_cfg.get("api_url", "https://api.openai.com/v1"),
        temperature=float(opt_cfg.get("temperature", 0.7)),
        max_retries=int(cfg.get("max_retries", 3)),
    )


def build_optimizer_agent_cfg(cfg: dict, overrides: dict) -> dict:
    opt_cfg = dict(cfg.get("optimizer", {}))
    if overrides.get("optimizer_model"):
        opt_cfg["model"] = overrides["optimizer_model"]
    api_key = _resolve_api_key(opt_cfg.get("api_key_env", "OPENAI_API_KEY"), "optimizer-agent")
    return {
        "model": opt_cfg.get("model", "gpt-4o"),
        "api_key": api_key,
        "api_url": opt_cfg.get("api_url", "https://api.openai.com/v1"),
    }


def main() -> None:
    # Load .env from project root (one level up from prompt_opt/)
    project_root = Path(__file__).parent.parent
    load_dotenv(project_root / ".env")

    parser = argparse.ArgumentParser(
        description="Prompt optimization workflow — hill-climb a prompt using LLM feedback.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to prompt_opt config.yaml (default: prompt_opt/config.yaml)",
    )
    parser.add_argument(
        "--initial-prompt",
        dest="initial_prompt",
        help="Override initial prompt file path",
    )
    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=None,
        help="Number of optimization iterations (overrides config)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Wall-clock timeout in seconds (overrides config)",
    )
    parser.add_argument(
        "--mode",
        choices=["direct", "agent"],
        default=None,
        help="Optimizer mode: 'direct' (API call) or 'agent' (DAGI AgentLoop)",
    )
    parser.add_argument(
        "--eval-model",
        dest="eval_model",
        default=None,
        help="Override eval model string (e.g. 'gpt-4o-mini')",
    )
    parser.add_argument(
        "--optimizer-model",
        dest="optimizer_model",
        default=None,
        help="Override optimizer model string (e.g. 'gpt-4o')",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Override output directory path",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-sample field errors during evaluation",
    )
    args = parser.parse_args()

    # Resolve config path
    prompt_opt_dir = Path(__file__).parent
    config_path = Path(args.config) if args.config else prompt_opt_dir / "config.yaml"
    cfg = load_config(config_path)
    config_dir = config_path.parent

    overrides = {
        "eval_model": args.eval_model,
        "optimizer_model": args.optimizer_model,
    }

    # Resolve paths
    data_dir = config_dir / cfg.get("data_dir", "data")
    output_dir = Path(args.output_dir) if args.output_dir else config_dir / cfg.get("output_dir", "output")

    # Load initial prompt
    if args.initial_prompt:
        initial_prompt_path = Path(args.initial_prompt)
    else:
        initial_prompt_path = config_dir / cfg.get("initial_prompt_file", "initial_prompt.txt")

    if not initial_prompt_path.exists():
        sys.exit(f"Initial prompt file not found: {initial_prompt_path}")
    initial_prompt = initial_prompt_path.read_text(encoding="utf-8").strip()

    # Determine optimizer mode
    optimizer_mode = args.mode or cfg.get("optimizer", {}).get("mode", "direct")

    # Build clients / configs
    from prompt_opt.optimizer import Optimizer, OptimizationConfig

    eval_client = build_eval_client(cfg, overrides)
    optimizer_llm_cfg = build_optimizer_llm_cfg(cfg, overrides)
    optimizer_agent_cfg = build_optimizer_agent_cfg(cfg, overrides)

    n_iterations = args.iterations if args.iterations is not None else int(cfg.get("n_iterations", 20))
    timeout_seconds = args.timeout if args.timeout is not None else cfg.get("timeout_seconds")

    opt_cfg = OptimizationConfig(
        n_iterations=n_iterations,
        timeout_seconds=timeout_seconds,
        data_dir=data_dir,
        output_dir=output_dir,
        initial_prompt=initial_prompt,
        eval_client=eval_client,
        optimizer_llm_cfg=optimizer_llm_cfg,
        optimizer_mode=optimizer_mode,
        optimizer_agent_cfg=optimizer_agent_cfg,
        max_retries=int(cfg.get("max_retries", 3)),
        verbose=args.verbose,
    )

    print(f"Config:      {config_path}")
    print(f"Data dir:    {data_dir}")
    print(f"Output dir:  {output_dir}")
    print(f"Mode:        {optimizer_mode}")
    print(f"Eval model:  {eval_client._cfg.model}")
    print(f"Iterations:  {n_iterations}  |  Timeout: {timeout_seconds}s")

    optimizer = Optimizer(opt_cfg)
    best = optimizer.run()

    print(f"\n=== Done ===")
    print(f"Best score:  {best.score:.1%} ({best.correct_fields}/{best.total_fields} fields)")
    print(f"Best prompt: {output_dir / 'best_prompt.txt'}")
    print(f"History:     {output_dir / 'history.json'}")
    print(f"Graph:       {output_dir / 'score_plot.png'}")


if __name__ == "__main__":
    main()
