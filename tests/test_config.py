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
