"""The only module that knows what an Update is. It refuses to start half-configured, gates who's
talking (unlimited owner/friends vs. rate-limited strangers), opens a connection for the turn, and
delivers the reply -- nothing else."""

from __future__ import annotations

import logging
import re
import sys
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
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
from julius.infra.llm_client import HttpLlmClient

log = logging.getLogger("julius.bot")

GREETING = (
    "Julius pronto. Pergunte um preço («quanto paguei de banana?»), compare mercados, ou peça uma "
    "correção do catálogo — escritas pedem confirmação."
)

NO_TOKEN = "JULIUS_BOT_TOKEN não definido — crie o bot no @BotFather e exporte o token."
NO_ALLOWLIST = (
    "JULIUS_BOT_ALLOWED_CHAT_ID não definido — o bot não sobe sem um dono. Para descobrir seu "
    "chat_id: exporte JULIUS_BOT_ALLOWED_CHAT_ID=0 (bootstrap, dono nenhum ainda), suba o bot, "
    'mande /start e leia "mensagem de chat_id=…" no log; depois exporte o número de verdade e '
    "reinicie."
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
    """Fail fast and loud: a bot that starts half-configured is one that dies on the first
    message, or has no owner to fall back to once a stranger hits the rate limit."""
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


RATE_LIMIT_WINDOW_SECONDS = 3600.0
RATE_LIMIT_REPLY = (
    "Chegou no limite de mensagens grátis por hora. Tenta de novo daqui a pouco, ou peça pra quem "
    "te chamou te colocar na lista sem limite."
)

# ponytail: janela fixa por chat_id, em memória de processo -- reinicia com o bot, mesmo trade-off
# já aceito pro ChatState (v2.6, PC doméstico que liga e desliga). Um Redis/SQLite valeria a pena
# se o limite precisasse sobreviver a reinícios frequentes; não é o caso hoje.
_rate_limit_state: dict[int, tuple[float, int]] = {}


def _unlimited(update: Update, settings: Config) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.id in settings.unlimited_chat_ids


def _allow_rate_limited(chat_id: int, limit: int, *, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    window_start, count = _rate_limit_state.get(chat_id, (now, 0))
    if now - window_start >= RATE_LIMIT_WINDOW_SECONDS:
        window_start, count = now, 0
    if count >= limit:
        _rate_limit_state[chat_id] = (window_start, count)
        return False
    _rate_limit_state[chat_id] = (window_start, count + 1)
    return True


async def _gate(update: Update, settings: Config) -> bool:
    """True quando esta mensagem pode ser processada agora. Diferente da allowlist antiga: o bot
    está aberto pra qualquer chat_id, sem confirmação nenhuma exigida -- só quem não está na lista
    sem limite (`unlimited_chat_ids`) esbarra na cota por hora, e é avisado disso, não ignorado em
    silêncio (o silêncio era o próprio bug que motivou abrir o bot: parecia travado)."""
    chat = update.effective_chat
    if chat is None:
        return False
    # Sempre logado, autorizado ou não -- é como o dono lê o próprio chat_id no bootstrap (era só
    # logado na recusa, antes de o bot aceitar qualquer chat_id).
    log.info("mensagem de chat_id=%s", chat.id)
    if _unlimited(update, settings):
        return True
    if _allow_rate_limited(chat.id, settings.bot_rate_limit_per_hour):
        return True
    log.info("chat_id=%s no limite de %s/h", chat.id, settings.bot_rate_limit_per_hour)
    await _send(update, RATE_LIMIT_REPLY)
    return False


def _keyboard(nonce: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm|{nonce}|y"),
                InlineKeyboardButton("❌ Cancelar", callback_data=f"confirm|{nonce}|n"),
            ]
        ]
    )


def _chunks(text: str) -> list[str]:
    """Um pensamento por bolha: a persona (e todo `f"{remark}\\n\\n{base}"` que este módulo já
    recebe) separa ideias por linha em branco desde a v2.7 -- só faltava o Telegram tratar isso
    como mensagens novas, em vez de parágrafo dentro da mesma bolha (design `bot-message-
    chunking.md`). `text` sem nenhuma linha em branco (o caso comum: "Nenhum resultado.", uma
    linha de fallback) vira uma lista de um item só, comportamento idêntico ao de antes."""
    return [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]


async def _send(update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    message = update.effective_message
    if message is None:
        return
    parts = _chunks(text) or [text]
    for index, part in enumerate(parts):
        # O teclado de confirmação só vai na última bolha -- é ela que carrega a pergunta.
        markup = keyboard if index == len(parts) - 1 else None
        try:
            await message.reply_text(part, parse_mode=ParseMode.HTML, reply_markup=markup)
        except BadRequest as error:
            if "parse" not in str(error).lower():
                raise
            # Um nome de produto exótico não pode silenciar o bot; o texto puro ainda é a resposta.
            log.warning("Telegram recusou o HTML (%s); reenviando sem formatação", error)
            await message.reply_text(part, reply_markup=markup)


def _settings_and_agent(context: ContextTypes.DEFAULT_TYPE) -> tuple[Config, BotAgent]:
    return context.bot_data["settings"], context.bot_data["agent"]


async def _show_typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The one low-cost finding from the humanization research
    (claudedocs/research_chatbot_humanizacao_20260918.md): a "digitando..." cue before the reply
    reads as more natural than an instant one. No `asyncio.sleep` on top of this -- the AI call's
    own latency (~1-2s, measured in the v2.7 smoke) already sits in the window the research calls
    ideal, and stacking an artificial delay on it would risk crossing the ~3s mark where perceived
    responsiveness drops. A failure here must never block the real reply."""
    chat = update.effective_chat
    if chat is None:
        return
    try:
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
    except Exception:
        log.debug("não consegui mandar o indicador de digitando", exc_info=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, _ = _settings_and_agent(context)
    if not await _gate(update, settings):
        return
    await _send(update, GREETING)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, agent = _settings_and_agent(context)
    if not await _gate(update, settings):
        return
    if update.message is None or not update.message.text:
        return
    await _show_typing(update, context)
    state = context.chat_data.setdefault("state", ChatState())
    conn = db.connect(settings.db_path)
    try:
        # _gate já retornou True: update.effective_chat não é None a esta altura.
        chat = update.effective_chat
        deps = Deps(
            conn=conn,
            config=settings,
            client=context.bot_data.get("client"),
            can_write=_unlimited(update, settings),
            chat_id=chat.id if chat else None,
        )
        reply = await handle_text(agent, state, deps, update.message.text)
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
    if not await _gate(update, settings):
        return
    try:
        _, nonce, verdict = (query.data or "").split("|", 2)
    except ValueError:
        return
    await _show_typing(update, context)
    state = context.chat_data.setdefault("state", ChatState())
    conn = db.connect(settings.db_path)
    try:
        deps = Deps(conn=conn, config=settings, client=context.bot_data.get("client"))
        reply = handle_tap(state, deps, nonce, verdict == "y")
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


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Long polling drops the connection now and then (rede caseira); a biblioteca já tenta de
    # novo sozinha (network_retry_loop, max_retries=-1) -- sem handler aqui, ela loga o traceback
    # inteiro como se o bot tivesse caído.
    log.warning("Falha de rede no polling, tentando de novo: %s", context.error)


def build_application(settings: Config, agent: BotAgent) -> Application:
    application = Application.builder().token(settings.bot_token).build()
    application.bot_data["settings"] = settings
    application.bot_data["agent"] = agent
    # Same client class every other suggestion call uses (ticket 166); None only when IA is not
    # configured, which check_startup already refuses to let the bot run without.
    application.bot_data["client"] = HttpLlmClient.from_config(settings)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(CallbackQueryHandler(on_tap, pattern=r"^confirm\|"))
    application.add_error_handler(on_error)
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
