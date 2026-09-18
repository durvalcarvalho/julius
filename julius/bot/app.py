"""The only module that knows what an Update is. It refuses to start open, checks who is talking,
opens a connection for the turn, and delivers the reply -- nothing else."""

from __future__ import annotations

import logging
import sys

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from julius import config
from julius.bot.actions import Deps
from julius.bot.agent import BotAgent, build_agent
from julius.bot.turn import DENIED_TAP, EXPIRED_TAP, STALE_TAP, ChatState, handle_tap, handle_text
from julius.config import Config
from julius.infra import db

log = logging.getLogger("julius.bot")

GREETING = (
    "Julius pronto. Pergunte um preço («quanto paguei de banana?»), compare mercados, ou peça uma "
    "correção do catálogo — escritas pedem confirmação."
)

NO_TOKEN = "JULIUS_BOT_TOKEN não definido — crie o bot no @BotFather e exporte o token."
NO_ALLOWLIST = (
    "JULIUS_BOT_ALLOWED_CHAT_ID não definido — o bot não sobe aberto. Para descobrir seu chat_id: "
    "exporte JULIUS_BOT_ALLOWED_CHAT_ID=0 (ninguém autorizado), suba o bot, mande /start e leia "
    '"mensagem ignorada de chat_id=…" no log; depois exporte o número e reinicie.'
)
NO_AI = (
    "IA não configurada (JULIUS_AI_API_KEY, JULIUS_AI_BASE_URL, JULIUS_AI_MODEL e os dois preços "
    "por token) — o bot roteia toda mensagem pela IA; não existe modo sem ela."
)

# The stamp left on the tapped message. Matched against the constants, not by prefix order: a
# stale tap and a failed write are different things, and one label for both would tell the user a
# write was attempted when none was.
_OUTCOMES = {
    STALE_TAP: "⚠️ Não está mais ativa",
    EXPIRED_TAP: "⏰ Expirado",
    DENIED_TAP: "❌ Cancelado",
}


def check_startup(settings: Config) -> None:
    """Fail fast and loud: a bot that starts half-configured is one that answers strangers or dies
    on the first message."""
    if not settings.bot_token:
        _die(NO_TOKEN)
    if settings.bot_allowed_chat_id is None:
        _die(NO_ALLOWLIST)
    if not (
        settings.ai_configured
        and settings.ai_input_price_usd_per_1m is not None
        and settings.ai_output_price_usd_per_1m is not None
    ):
        _die(NO_AI)


def _die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def configure_logging() -> None:
    """httpx at INFO prints the getUpdates URL, and the token is inside it."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _authorized(update: Update, settings: Config) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.id == settings.bot_allowed_chat_id


def _refuse(update: Update) -> None:
    """Silence, not "acesso negado": an answer would confirm there is someone here. The line is
    also the bootstrap -- it is where the owner reads their own chat_id the first time."""
    chat = update.effective_chat
    log.info("mensagem ignorada de chat_id=%s (fora da allowlist)", chat.id if chat else None)


def _keyboard(nonce: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm|{nonce}|y"),
                InlineKeyboardButton("❌ Cancelar", callback_data=f"confirm|{nonce}|n"),
            ]
        ]
    )


async def _send(update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    message = update.effective_message
    if message is None:
        return
    try:
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except BadRequest as error:
        if "parse" not in str(error).lower():
            raise
        # An exotic product name must not silence the bot; the plain text is still the answer.
        log.warning("Telegram recusou o HTML (%s); reenviando sem formatação", error)
        await message.reply_text(text, reply_markup=keyboard)


def _settings_and_agent(context: ContextTypes.DEFAULT_TYPE) -> tuple[Config, BotAgent]:
    return context.bot_data["settings"], context.bot_data["agent"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, _ = _settings_and_agent(context)
    if not _authorized(update, settings):
        _refuse(update)
        return
    await _send(update, GREETING)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, agent = _settings_and_agent(context)
    if not _authorized(update, settings):
        _refuse(update)
        return
    if update.message is None or not update.message.text:
        return
    state = context.chat_data.setdefault("state", ChatState())
    conn = db.connect(settings.db_path)
    try:
        reply = await handle_text(agent, state, Deps(conn=conn, config=settings), update.message.text)
    finally:
        conn.close()
    await _send(update, reply.text, _keyboard(reply.pending.nonce) if reply.pending else None)


def _outcome(text: str) -> str:
    if text in _OUTCOMES:
        return _OUTCOMES[text]
    return "✅ Confirmado" if text.startswith("✅") else "⚠️ Não executado"


async def on_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, _ = _settings_and_agent(context)
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    if not _authorized(update, settings):
        _refuse(update)
        return
    try:
        _, nonce, verdict = (query.data or "").split("|", 2)
    except ValueError:
        return
    state = context.chat_data.setdefault("state", ChatState())
    conn = db.connect(settings.db_path)
    try:
        reply = handle_tap(state, Deps(conn=conn, config=settings), nonce, verdict == "y")
    finally:
        conn.close()
    try:
        await query.edit_message_text(
            f"{query.message.text}\n\n{_outcome(reply.text)}" if query.message else _outcome(reply.text),
            reply_markup=None,
        )
    except BadRequest as error:
        log.debug("não consegui editar a mensagem do botão: %s", error)
    await _send(update, reply.text)


def build_application(settings: Config, agent: BotAgent) -> Application:
    application = Application.builder().token(settings.bot_token).build()
    application.bot_data["settings"] = settings
    application.bot_data["agent"] = agent
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(CallbackQueryHandler(on_tap, pattern=r"^confirm\|"))
    return application


def main() -> None:
    settings = config.load()
    check_startup(settings)
    # Open once so pending migrations run now, not inside the first turn.
    db.connect(settings.db_path).close()
    configure_logging()
    application = build_application(settings, build_agent(settings))
    log.info("Julius no ar, ouvindo o chat %s", settings.bot_allowed_chat_id)
    application.run_polling(
        allowed_updates=["message", "callback_query"],
        # What arrived while the PC was off is not answered on the way back: unavailable is
        # unavailable, and a week-old "quanto custa X" answered now is noise.
        drop_pending_updates=True,
    )
