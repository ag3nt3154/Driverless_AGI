"""
telegram_bot.py — Telegram bot interface for Driverless AGI.

Usage:
    conda run -n dagi python telegram_bot.py
    conda run -n dagi python telegram_bot.py --model deepseek-v4-flash-openrouter
    conda run -n dagi python telegram_bot.py --project /path/to/project
"""
import logging
import os
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

load_dotenv()

from agent.config_loader import load_telegram_config  # noqa: E402
from tg import TelegramBot  # noqa: E402

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)

_cli = typer.Typer(name="dagi-telegram", add_completion=False)


@_cli.command()
def main(
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Model ID from config.yaml"
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project directory"
    ),
) -> None:
    """Start the DAGI Telegram bot."""
    tg_config = load_telegram_config()
    token = tg_config.bot_token

    if not token:
        typer.echo(
            "Error: Telegram bot token not found.\n"
            "Set TELEGRAM_BOT_TOKEN in .env or configure "
            "telegram.bot_token_env in config.yaml.",
            err=True,
        )
        raise typer.Exit(1)

    project_path = Path(project).resolve() if project else None
    bot = TelegramBot(token=token, model_id=model, project_path=project_path)
    bot.run()


if __name__ == "__main__":
    _cli()
