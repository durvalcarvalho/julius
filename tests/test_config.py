from pathlib import Path

import pytest

from julius import config


def test_defaults_when_env_is_empty():
    cfg = config.load({})
    assert cfg.db_path == config.DEFAULT_DB_PATH
    assert cfg.ai_api_key is None
    assert cfg.ai_base_url is None
    assert cfg.ai_model is None
    assert cfg.ai_budget_usd == 1.0
    assert cfg.ai_input_price_usd_per_1m is None
    assert cfg.ai_output_price_usd_per_1m is None
    assert cfg.ai_configured is False


def test_env_overrides_everything():
    cfg = config.load(
        {
            "JULIUS_DB": "/tmp/x.db",
            "JULIUS_AI_API_KEY": "secret",
            "JULIUS_AI_BASE_URL": "https://api.example/v1",
            "JULIUS_AI_MODEL": "cheap-1",
            "JULIUS_AI_BUDGET_USD": "0.5",
            "JULIUS_AI_INPUT_PRICE_USD_PER_1M": "0.15",
            "JULIUS_AI_OUTPUT_PRICE_USD_PER_1M": "0.6",
        }
    )
    assert cfg.db_path == Path("/tmp/x.db")
    assert cfg.ai_configured is True
    assert cfg.ai_budget_usd == 0.5
    assert cfg.ai_input_price_usd_per_1m == 0.15
    assert cfg.ai_output_price_usd_per_1m == 0.6


def test_ai_is_not_configured_with_only_an_api_key():
    cfg = config.load({"JULIUS_AI_API_KEY": "secret"})
    assert cfg.ai_configured is False


def test_zero_budget_is_kept_not_replaced_by_default():
    assert config.load({"JULIUS_AI_BUDGET_USD": "0"}).ai_budget_usd == 0.0


def test_empty_string_counts_as_unset():
    cfg = config.load({"JULIUS_DB": "", "JULIUS_AI_BUDGET_USD": "", "JULIUS_AI_API_KEY": ""})
    assert cfg.db_path == config.DEFAULT_DB_PATH
    assert cfg.ai_budget_usd == 1.0
    assert cfg.ai_api_key is None


def test_non_numeric_budget_fails_loudly_naming_the_variable():
    with pytest.raises(ValueError, match="JULIUS_AI_BUDGET_USD"):
        config.load({"JULIUS_AI_BUDGET_USD": "um dolar"})


def test_load_reads_the_process_environment_by_default(monkeypatch):
    monkeypatch.setenv("JULIUS_DB", "/tmp/from-env.db")
    assert config.load().db_path == Path("/tmp/from-env.db")


def test_request_extras_default_is_empty_dict():
    assert config.load({}).ai_request_extras == {}


def test_request_extras_parses_json_object():
    cfg = config.load({"JULIUS_AI_REQUEST_EXTRAS": '{"thinking":{"type":"disabled"}}'})
    assert cfg.ai_request_extras == {"thinking": {"type": "disabled"}}


@pytest.mark.parametrize("raw", ["[1]", "42", "{oops"])
def test_request_extras_rejects_non_object_or_invalid_json(raw):
    with pytest.raises(ValueError, match="JULIUS_AI_REQUEST_EXTRAS"):
        config.load({"JULIUS_AI_REQUEST_EXTRAS": raw})


def test_ai_log_path_sits_next_to_db():
    cfg = config.load({"JULIUS_DB": "/x/y/prices.db"})
    assert cfg.ai_log_path == Path("/x/y/ai_calls.jsonl")


def test_query_log_path_sits_next_to_db():
    cfg = config.load({"JULIUS_DB": "/x/y/prices.db"})
    assert cfg.query_log_path == Path("/x/y/query_log.jsonl")


def test_action_log_path_sits_next_to_db():
    cfg = config.load({"JULIUS_DB": "/x/y/prices.db"})
    assert cfg.action_log_path == Path("/x/y/actions.jsonl")


def test_inbox_and_archive_paths_sit_next_to_db():
    cfg = config.load({"JULIUS_DB": "/x/y/prices.db"})
    assert cfg.inbox_path == Path("/x/y/entrada")
    assert cfg.archive_path == Path("/x/y/entrada/importados")


def test_bot_settings_default_to_none_and_not_configured():
    cfg = config.load({})
    assert cfg.bot_token is None
    assert cfg.bot_allowed_chat_id is None
    assert cfg.bot_configured is False


def test_bot_settings_are_read_from_env():
    cfg = config.load({"JULIUS_BOT_TOKEN": "123:abc", "JULIUS_BOT_ALLOWED_CHAT_ID": "123456789"})
    assert cfg.bot_token == "123:abc"
    assert cfg.bot_allowed_chat_id == 123456789
    assert cfg.bot_configured is True


def test_bot_token_alone_is_not_configured():
    assert config.load({"JULIUS_BOT_TOKEN": "123:abc"}).bot_configured is False


def test_bot_allowed_chat_id_alone_is_not_configured():
    assert config.load({"JULIUS_BOT_ALLOWED_CHAT_ID": "7"}).bot_configured is False


@pytest.mark.parametrize("raw", ["abc", "12.5"])
def test_bot_allowed_chat_id_must_be_an_integer(raw):
    """A float is an error too: a chat id is compared for equality, and 12.5 can never match one."""
    with pytest.raises(ValueError, match="JULIUS_BOT_ALLOWED_CHAT_ID"):
        config.load({"JULIUS_BOT_ALLOWED_CHAT_ID": raw})


def test_a_group_chat_id_is_negative_and_accepted():
    assert config.load({"JULIUS_BOT_ALLOWED_CHAT_ID": "-1001234567890"}).bot_allowed_chat_id == -1001234567890


def test_zero_is_a_configured_chat_id_because_it_is_the_bootstrap():
    """No real chat has id 0, so nobody real is ever the owner by accident: everyone with a real
    chat_id falls back to the hourly rate limit until the owner exports their real number."""
    cfg = config.load({"JULIUS_BOT_TOKEN": "123:abc", "JULIUS_BOT_ALLOWED_CHAT_ID": "0"})
    assert cfg.bot_allowed_chat_id == 0
    assert cfg.bot_configured is True


def test_unlimited_chat_ids_always_include_the_owner():
    cfg = config.load({"JULIUS_BOT_ALLOWED_CHAT_ID": "1", "JULIUS_BOT_UNLIMITED_CHAT_IDS": "2, 3"})
    assert cfg.unlimited_chat_ids == frozenset({1, 2, 3})


def test_unlimited_chat_ids_without_an_owner_is_just_the_extra_list():
    assert config.load({"JULIUS_BOT_UNLIMITED_CHAT_IDS": "5"}).unlimited_chat_ids == frozenset({5})


def test_unlimited_chat_ids_must_be_integers():
    with pytest.raises(ValueError, match="JULIUS_BOT_UNLIMITED_CHAT_IDS"):
        config.load({"JULIUS_BOT_UNLIMITED_CHAT_IDS": "1,abc"})


def test_rate_limit_defaults_to_20_per_hour():
    assert config.load({}).bot_rate_limit_per_hour == 20


def test_rate_limit_is_read_from_env():
    assert config.load({"JULIUS_BOT_RATE_LIMIT_PER_HOUR": "5"}).bot_rate_limit_per_hour == 5


def test_conftest_isolates_bot_env():
    """The user exports a real token in their shell. `load()` with no argument reads os.environ,
    so this only passes because the autouse fixture deleted both names first -- and the membership
    check is what fails loudly if someone trims that list."""
    from conftest import ISOLATED_ENV_VARS

    assert {
        "JULIUS_BOT_TOKEN",
        "JULIUS_BOT_ALLOWED_CHAT_ID",
        "JULIUS_BOT_UNLIMITED_CHAT_IDS",
        "JULIUS_BOT_RATE_LIMIT_PER_HOUR",
    } <= set(ISOLATED_ENV_VARS)
    cfg = config.load()
    assert cfg.bot_token is None
    assert cfg.bot_allowed_chat_id is None
