"""Core Telegram bot class — handlers, lifecycle, async/sync bridge."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent.config_loader import resolve_model_config
from agent.loop import AgentLoop

from .callbacks import build_callbacks
from .session import SessionManager

logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram interface for DAGI's AgentLoop."""

    def __init__(
        self,
        token: str,
        model_id: str | None = None,
        project_path: Path | None = None,
        allowed_chat_ids: frozenset[int] | None = None,
    ) -> None:
        self._token = token
        self._model_id = model_id
        self._project_path = (
            project_path.resolve() if project_path else Path.cwd()
        )
        self._allowed_chat_ids = allowed_chat_ids or frozenset()
        self._sessions = SessionManager()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        if not self._allowed_chat_ids:
            logger.warning(
                "TELEGRAM_ALLOWED_CHAT_IDS is not set — this bot will respond "
                "to any Telegram user who finds it, including running shell "
                "commands. Set TELEGRAM_ALLOWED_CHAT_IDS (comma-separated chat "
                "IDs) to restrict access."
            )

    def _is_authorized(self, chat_id: int) -> bool:
        return not self._allowed_chat_ids or chat_id in self._allowed_chat_ids

    def run(self) -> None:
        """Start the bot (blocking). Sets up handlers and begins polling."""
        app = Application.builder().token(self._token).build()

        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("clear", self._cmd_clear))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        app.post_init = self._post_init
        logger.info("DAGI Telegram bot starting — polling for updates…")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

    async def _post_init(self, application: Application) -> None:
        """Capture the running event loop after the Application starts."""
        self._event_loop = asyncio.get_running_loop()

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_authorized(update.effective_chat.id):
            return
        await update.message.send_chat_action(ChatAction.TYPING)
        await update.message.reply_text(
            "Bonjour, Admiral! DAGI is at your service.\n\n"
            "Send me any task and I will work on it.\n\n"
            "Commands:\n"
            "/clear — Reset conversation\n"
            "/help — Show this message"
        )

    async def _cmd_clear(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            return
        session = self._sessions.get_or_create(chat_id)
        if session.busy:
            await update.message.reply_text(
                "Agent is currently working. Please wait for it to finish."
            )
            return
        self._sessions.clear(chat_id)
        await update.message.reply_text("Conversation cleared — fresh session.")

    async def _cmd_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_authorized(update.effective_chat.id):
            return
        await update.message.reply_text(
            "DAGI Telegram Bot\n\n"
            "Send any message to give DAGI a task.\n"
            "Multi-turn conversations are supported — "
            "context carries over between messages.\n\n"
            "Commands:\n"
            "/start — Welcome message\n"
            "/clear — Reset conversation history\n"
            "/help — Show this message"
        )

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Route incoming text: answer pending ask_user or dispatch new task."""
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            logger.warning("Rejected message from unauthorized chat_id %s", chat_id)
            return
        text = update.message.text or ""
        session = self._sessions.get_or_create(chat_id)

        if session.pending_ask is not None:
            evt, container = session.pending_ask
            container.append(text)
            evt.set()
            return

        if session.busy:
            await update.message.reply_text(
                "Agent is still working on the previous task. Please wait."
            )
            return

        await self._run_agent_task(chat_id, text, update)

    async def _run_agent_task(
        self, chat_id: int, task: str, update: Update
    ) -> None:
        """Bridge: run AgentLoop synchronously in an executor thread."""
        session = self._sessions.get_or_create(chat_id)
        session.busy = True

        await update.message.send_chat_action(ChatAction.TYPING)

        loop = None
        try:
            config = resolve_model_config(
                self._model_id, project_path=self._project_path
            )
            config.project_path = self._project_path

            bot_obj = update.get_bot()
            cbs = build_callbacks(
                bot=bot_obj,
                chat_id=chat_id,
                session=session,
                event_loop=self._event_loop,
            )

            loop = AgentLoop(
                config,
                callbacks=cbs,
                initial_messages=session.messages,
            )

            await asyncio.get_event_loop().run_in_executor(
                None, loop.run, task
            )
        except Exception as exc:
            logger.exception("Agent task failed for chat %s", chat_id)
            try:
                await update.message.reply_text(f"Error: {exc}")
            except Exception:
                pass
        finally:
            if loop:
                session.messages = loop._messages
                loop.finish()
            session.busy = False
