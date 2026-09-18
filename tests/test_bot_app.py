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


@pytest.mark.parametrize(
    ("reply_text", "expected"),
    [
        ("✅ Produto 1 agora é «X»", "✅ Confirmado"),
        ("❌ Cancelado — nada foi executado.", "❌ Cancelado"),
        ("Confirmação expirada — nada foi executado.", "⏰ Expirado"),
        ("❌ Não executado: deu ruim", "⚠️ Não executado"),
        ("Essa confirmação não está mais ativa.", "⚠️ Não executado"),
    ],
)
def test_outcome_labels_every_reply_the_tap_can_produce(reply_text, expected):
    assert bot_app._outcome(reply_text) == expected


def test_importing_the_app_has_no_side_effects_on_disk(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "JULIUS_DB": str(tmp_path / "x.db")}
    subprocess.run([sys.executable, "-c", "import julius.bot.app"], check=True, env=env, cwd=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_the_bot_reads_no_environment_of_its_own():
    """Every variable goes through config.load(); a second reader would drift from it."""
    from pathlib import Path

    sources = list(Path("julius/bot").glob("*.py"))
    assert sources
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "os.environ" not in text, path
        assert "getenv" not in text, path
