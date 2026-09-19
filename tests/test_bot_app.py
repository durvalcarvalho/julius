import logging
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from julius import config as config_module
from julius.bot import app as bot_app
from julius.bot.agent import build_agent

FULL_ENV = {
    "JULIUS_BOT_TOKEN": "123:abc",
    "JULIUS_BOT_ALLOWED_CHAT_ID": "42",
    "JULIUS_AI_API_KEY": "k",
    "JULIUS_AI_BASE_URL": "https://x/v1",
    "JULIUS_AI_MODEL": "m",
    "JULIUS_AI_INPUT_PRICE_USD_PER_1M": "0.30",
    "JULIUS_AI_OUTPUT_PRICE_USD_PER_1M": "1.20",
}


def _settings(**overrides):
    env = {**FULL_ENV, **overrides}
    return config_module.load({k: v for k, v in env.items() if v is not None})


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ("JULIUS_BOT_TOKEN", "JULIUS_BOT_TOKEN"),
        ("JULIUS_BOT_ALLOWED_CHAT_ID", "chat_id"),
        ("JULIUS_AI_API_KEY", "JULIUS_AI_API_KEY"),
        ("JULIUS_AI_INPUT_PRICE_USD_PER_1M", "preços"),
    ],
)
def test_check_startup_refuses_to_start_half_configured(capsys, missing, expected):
    with pytest.raises(SystemExit) as exit_info:
        bot_app.check_startup(_settings(**{missing: None}))

    assert exit_info.value.code == 2
    assert expected in capsys.readouterr().err


def test_check_startup_without_allowlist_explains_the_bootstrap(capsys):
    with pytest.raises(SystemExit):
        bot_app.check_startup(_settings(JULIUS_BOT_ALLOWED_CHAT_ID=None))

    error = capsys.readouterr().err
    assert "/start" in error
    assert "JULIUS_BOT_ALLOWED_CHAT_ID=0" in error


def test_check_startup_passes_when_everything_is_set():
    bot_app.check_startup(_settings())


def _update(chat_id):
    return SimpleNamespace(effective_chat=None if chat_id is None else SimpleNamespace(id=chat_id))


def test_authorized_compares_effective_chat_id():
    settings = _settings(JULIUS_BOT_ALLOWED_CHAT_ID="1")

    assert bot_app._authorized(_update(1), settings) is True
    assert bot_app._authorized(_update(2), settings) is False
    assert bot_app._authorized(_update(None), settings) is False


def test_bootstrap_zero_authorizes_nobody():
    """No Telegram chat has id 0, so the bot starts configured and still closed -- it only logs who
    wrote, which is how the owner learns their own id."""
    settings = _settings(JULIUS_BOT_ALLOWED_CHAT_ID="0")

    assert settings.bot_configured is True
    for chat_id in (1, -1001234567890, 999999999):
        assert bot_app._authorized(_update(chat_id), settings) is False


def test_keyboard_callback_data_carries_the_nonce():
    buttons = bot_app._keyboard("abc").inline_keyboard[0]

    assert [button.callback_data for button in buttons] == ["confirm|abc|y", "confirm|abc|n"]
    assert len(buttons) == 2


def test_configure_logging_caps_httpx_and_httpcore():
    """At INFO, httpx logs the getUpdates URL -- and the token is inside it."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.NOTSET)

    bot_app.configure_logging()

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_build_application_registers_three_handlers():
    settings = _settings()
    agent = build_agent(settings, model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("x")])))

    application = bot_app.build_application(settings, agent)

    assert len(application.handlers[0]) == 3
    assert application.bot_data["agent"] is agent
    assert application.bot_data["settings"] is settings
    assert application.error_handlers


def test_build_application_stores_a_client_when_ai_is_configured():
    from julius.infra.llm_client import HttpLlmClient

    settings = _settings()
    agent = build_agent(settings, model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("x")])))

    application = bot_app.build_application(settings, agent)

    assert isinstance(application.bot_data["client"], HttpLlmClient)


@pytest.mark.parametrize(
    ("reply_text", "expected"),
    [
        ("✅ Produto 1 agora é «X»", "✅ Confirmado"),
        ("❌ Cancelado — nada foi executado.", "❌ Cancelado"),
        ("Confirmação expirada — nada foi executado.", "⏰ Expirado"),
        ("❌ Não executado: deu ruim", "⚠️ Não executado"),
        ("Essa confirmação não está mais ativa.", "⚠️ Não está mais ativa"),
    ],
)
def test_outcome_labels_every_reply_the_tap_can_produce(reply_text, expected):
    assert bot_app._outcome(reply_text) == expected


def test_a_stale_tap_and_a_failed_write_are_stamped_differently():
    """Both leave the database alone, but only one of them was ever attempted -- the same label on
    both would tell the user a write failed when none was tried."""
    from julius.bot import turn

    assert bot_app._outcome(turn.STALE_TAP) != bot_app._outcome("❌ Não executado: deu ruim")


def test_every_reply_handle_tap_can_return_has_a_label():
    from julius.bot import turn

    for text in (turn.STALE_TAP, turn.EXPIRED_TAP, turn.DENIED_TAP):
        assert bot_app._outcome(text) != "⚠️ Não executado", text


def test_importing_the_app_has_no_side_effects_on_disk(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "JULIUS_DB": str(tmp_path / "x.db")}
    subprocess.run([sys.executable, "-c", "import julius.bot.app"], check=True, env=env, cwd=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_the_bot_reads_no_environment_of_its_own():
    """Every variable goes through config.load(); a second reader would drift from it."""
    from pathlib import Path

    sources = list((Path(__file__).resolve().parent.parent / "julius" / "bot").glob("*.py"))
    assert sources
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "os.environ" not in text, path
        assert "getenv" not in text, path


# --- "digitando..." (ticket 173) ---------------------------------------------------

import asyncio  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

from telegram.constants import ChatAction  # noqa: E402


def _context_with_bot():
    return SimpleNamespace(bot=AsyncMock())


def test_show_typing_sends_the_action_for_the_right_chat():
    context = _context_with_bot()

    asyncio.run(bot_app._show_typing(_update(42), context))

    context.bot.send_chat_action.assert_awaited_once_with(chat_id=42, action=ChatAction.TYPING)


def test_show_typing_without_a_chat_sends_nothing():
    context = _context_with_bot()

    asyncio.run(bot_app._show_typing(_update(None), context))

    context.bot.send_chat_action.assert_not_awaited()


def test_show_typing_failure_is_swallowed():
    context = _context_with_bot()
    context.bot.send_chat_action.side_effect = RuntimeError("rede caiu")

    asyncio.run(bot_app._show_typing(_update(42), context))  # must not raise


# --- várias mensagens por resposta (design bot-message-chunking.md) --------------


def _message_update():
    message = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(effective_message=message), message


def test_chunks_splits_on_blank_lines():
    assert bot_app._chunks("primeiro\n\nsegundo\n\nterceiro") == ["primeiro", "segundo", "terceiro"]


def test_chunks_keeps_single_line_breaks_inside_one_bubble():
    assert bot_app._chunks("linha 1\nlinha 2") == ["linha 1\nlinha 2"]


def test_chunks_of_text_with_no_blank_line_is_a_single_chunk():
    assert bot_app._chunks("Nenhum resultado.") == ["Nenhum resultado."]


def test_chunks_tolerates_three_or_more_blank_lines():
    assert bot_app._chunks("a\n\n\nb") == ["a", "b"]


def test_send_delivers_one_message_per_block():
    update, message = _message_update()

    asyncio.run(bot_app._send(update, "primeiro bloco\n\nsegundo bloco\n\nterceiro bloco"))

    assert message.reply_text.await_count == 3
    texts = [call.args[0] for call in message.reply_text.await_args_list]
    assert texts == ["primeiro bloco", "segundo bloco", "terceiro bloco"]


def test_send_of_a_single_block_is_unchanged():
    update, message = _message_update()

    asyncio.run(bot_app._send(update, "Nenhum resultado."))

    message.reply_text.assert_awaited_once()
    assert message.reply_text.await_args.args[0] == "Nenhum resultado."


def test_send_puts_the_keyboard_only_on_the_last_message():
    update, message = _message_update()
    keyboard = bot_app._keyboard("abc")

    asyncio.run(bot_app._send(update, "bloco 1\n\nbloco 2", keyboard))

    markups = [call.kwargs["reply_markup"] for call in message.reply_text.await_args_list]
    assert markups == [None, keyboard]


def test_send_with_no_effective_message_does_nothing():
    update = SimpleNamespace(effective_message=None)

    asyncio.run(bot_app._send(update, "oi"))  # must not raise


def test_send_recovers_per_chunk_when_telegram_refuses_the_html():
    """Uma bolha com HTML exótico não pode derrubar as outras -- cada uma recua sozinha."""
    from telegram.error import BadRequest

    message = SimpleNamespace(reply_text=AsyncMock(side_effect=[BadRequest("can't parse entities"), None, None]))
    update = SimpleNamespace(effective_message=message)

    asyncio.run(bot_app._send(update, "bloco <ruim\n\nbloco ok"))

    assert message.reply_text.await_count == 3, "1 tentativa com HTML + 1 recuo pro 1º bloco, + 1 chamada normal pro 2º"
    first_attempt, recovered, second_block = message.reply_text.await_args_list
    assert first_attempt.kwargs.get("parse_mode") is not None
    assert "parse_mode" not in recovered.kwargs
    assert second_block.kwargs.get("parse_mode") is not None


def test_no_module_level_sleep_is_used_for_the_typing_delay():
    """Deliberate: the AI call's own latency already sits in the window the research calls ideal;
    stacking a fixed sleep on top of it risks crossing the ~3s mark where perceived
    responsiveness drops (see _show_typing's docstring and ticket 173)."""
    from pathlib import Path

    text = (Path(bot_app.__file__)).read_text(encoding="utf-8")
    assert "asyncio.sleep(" not in text
