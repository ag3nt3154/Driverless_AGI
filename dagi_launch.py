"""
dagi_launch.py — Interactive launcher for the Driverless AGI TUI.

Prompts for a default model (from config.yaml's `models` catalog) and a
verbose on/off toggle, then launches tui.py with the corresponding args.

Usage:
    python dagi_launch.py
"""
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / ".dagi" / "config.yaml"


def load_models() -> tuple[dict, str | None]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    models = config.get("models", {})
    default_model = config.get("default_model")
    return models, default_model


def prompt_model(models: dict, default_model: str | None) -> str:
    model_ids = list(models.keys())
    print("Available models:")
    for i, model_id in enumerate(model_ids, start=1):
        name = models[model_id].get("name", model_id)
        marker = "  (current default)" if model_id == default_model else ""
        print(f"  {i}. {name} [{model_id}]{marker}")

    while True:
        choice = input(f"Select a model [1-{len(model_ids)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(model_ids):
            return model_ids[int(choice) - 1]
        print("Invalid selection, try again.")


def prompt_verbose() -> bool:
    while True:
        choice = input("Verbose mode? [y/n]: ").strip().lower()
        if choice in ("y", "yes", "true"):
            return True
        if choice in ("n", "no", "false"):
            return False
        print("Please enter y or n.")


def main() -> None:
    models, default_model = load_models()
    if not models:
        print(f"No models found in {CONFIG_PATH}")
        sys.exit(1)

    model_id = prompt_model(models, default_model)
    verbose = prompt_verbose()

    args = [sys.executable, str(ROOT / "tui.py"), "--model", model_id]
    if verbose:
        args.append("--verbose")

    subprocess.run(args, cwd=str(ROOT))


if __name__ == "__main__":
    main()
