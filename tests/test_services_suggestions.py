import json
from dataclasses import replace

import pytest

from _fakes import RaisingLlmClient, ScriptedLlmClient
from julius.config import Config
from julius.domain.models import MergeSuggestion
from julius.infra.llm_client import LlmResponse
from julius.repositories import ai_usage
from julius.services import suggestions

MONTH = "2026-09"


@pytest.fixture
def cfg(db_path) -> Config:
    return Config(
        db_path=db_path,
        ai_api_key="secret",
        ai_base_url="https://api.example/v1",
        ai_model="cheap-1",
        ai_budget_usd=1.0,
        ai_input_price_usd_per_1m=1.0,
        ai_output_price_usd_per_1m=1.0,
    )


def _merge_response(payload: dict, input_tokens: int = 1000, output_tokens: int = 500) -> LlmResponse:
    return LlmResponse(json.dumps(payload), input_tokens, output_tokens)


def _lines(cfg: Config) -> list[dict]:
    return [json.loads(line) for line in cfg.ai_log_path.read_text(encoding="utf-8").splitlines()]


def test_not_configured_returns_none_without_call_or_log_line(conn, cfg):
    config = replace(cfg, ai_api_key=None)
    client = ScriptedLlmClient([_merge_response({"pairs": []})])
    assert suggestions.suggest_merges(conn, config, client, [("A", "B")], MONTH) == [None]
    assert client.calls == []
    assert not config.ai_log_path.exists()


def test_budget_exhausted_logs_one_line_and_does_not_call(conn, cfg):
    ai_usage.add_spent(conn, MONTH, cfg.ai_budget_usd)
    client = ScriptedLlmClient([_merge_response({"pairs": []})])
    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B")], MONTH)
    assert result == [None]
    assert client.calls == []
    (line,) = _lines(cfg)
    assert line["error"] == "budget_exhausted"
    assert line["attempt"] == 0


def test_suggest_merges_parses_batch_in_order_and_records_cost(conn, cfg):
    payload = {
        "pairs": [
            {"id": 3, "rationale": "r3", "same_product": False, "confidence": 0.2},
            {"id": 1, "rationale": "r1", "same_product": True, "confidence": 0.9},
            {"id": 2, "rationale": "r2", "same_product": True, "confidence": 0.5},
        ]
    }
    client = ScriptedLlmClient([_merge_response(payload, input_tokens=1000, output_tokens=500)])
    pairs = [("A1", "B1"), ("A2", "B2"), ("A3", "B3")]

    result = suggestions.suggest_merges(conn, cfg, client, pairs, MONTH)

    assert result == [
        MergeSuggestion(True, 0.9, "r1"),
        MergeSuggestion(True, 0.5, "r2"),
        MergeSuggestion(False, 0.2, "r3"),
    ]
    assert ai_usage.spent_in_month(conn, MONTH) == pytest.approx(1000 / 1e6 + 500 / 1e6)


def test_invalid_json_then_valid_retries_once_and_charges_both(conn, cfg):
    valid = {"pairs": [{"id": 1, "rationale": "r", "same_product": True, "confidence": 0.5}]}
    client = ScriptedLlmClient([LlmResponse("não sei", 100, 50), _merge_response(valid, 200, 100)])

    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B")], MONTH)

    assert result == [MergeSuggestion(True, 0.5, "r")]
    assert len(client.calls) == 2
    lines = _lines(cfg)
    assert [line["attempt"] for line in lines] == [1, 2]
    assert [line["parsed_ok"] for line in lines] == [False, True]
    expected_cost = (100 / 1e6 + 50 / 1e6) + (200 / 1e6 + 100 / 1e6)
    assert ai_usage.spent_in_month(conn, MONTH) == pytest.approx(expected_cost)


def test_two_failures_return_none_for_every_pair_after_two_calls(conn, cfg):
    client = ScriptedLlmClient([LlmResponse("nope", 10, 10), LlmResponse("nope2", 10, 10)])
    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B"), ("C", "D")], MONTH)
    assert result == [None, None]
    assert len(client.calls) == 2


def test_transport_error_is_logged_with_error_text(conn, cfg):
    client = ScriptedLlmClient([LlmResponse("", 0, 0, error="HTTP 429")])
    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B")], MONTH)
    assert result == [None]
    lines = _lines(cfg)
    assert lines[-1]["error"] == "HTTP 429"
    assert lines[-1]["cost_usd"] == 0


def test_truncated_response_is_charged(conn, cfg):
    client = ScriptedLlmClient([LlmResponse("", 1200, 1200, error="finish_reason length")])
    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B")], MONTH)
    assert result == [None]
    assert ai_usage.spent_in_month(conn, MONTH) > 0


def test_client_raising_never_propagates_and_is_logged_as_client_raised(conn, cfg):
    result = suggestions.suggest_merges(conn, cfg, RaisingLlmClient(), [("A", "B")], MONTH)
    assert result == [None]
    lines = _lines(cfg)
    assert all(line["error"] == "client raised RuntimeError" for line in lines)


def test_item_with_invalid_fields_becomes_none_but_others_survive(conn, cfg):
    payload = {
        "pairs": [
            {"id": 1, "rationale": "ok", "same_product": True, "confidence": 1.5},
            {"id": 2, "rationale": "ok", "same_product": "sim", "confidence": 0.5},
            {"id": 3, "rationale": "ok", "same_product": True, "confidence": 0.5},
        ]
    }
    client = ScriptedLlmClient([_merge_response(payload)])

    result = suggestions.suggest_merges(conn, cfg, client, [("A", "B"), ("C", "D"), ("E", "F")], MONTH)

    assert result[0] is None
    assert result[1] is None
    assert result[2] == MergeSuggestion(True, 0.5, "ok")


def test_log_line_has_exact_keys(conn, cfg):
    payload = {"pairs": [{"id": 1, "rationale": "r", "same_product": True, "confidence": 0.5}]}
    client = ScriptedLlmClient([_merge_response(payload)])
    suggestions.suggest_merges(conn, cfg, client, [("A", "B")], MONTH)
    (line,) = _lines(cfg)
    assert set(line) == {
        "ts",
        "call_kind",
        "prompt_version",
        "model",
        "attempt",
        "user_prompt",
        "raw_response",
        "parsed_ok",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "latency_ms",
        "error",
    }


def test_max_tokens_scales_with_pair_count(conn, cfg):
    client = ScriptedLlmClient([_merge_response({"pairs": []})])
    suggestions.suggest_merges(conn, cfg, client, [("A", "B")] * 4, MONTH)
    assert client.calls[0][2] == 420


def test_empty_pairs_returns_empty_without_call(conn, cfg):
    client = ScriptedLlmClient([_merge_response({"pairs": []})])
    assert suggestions.suggest_merges(conn, cfg, client, [], MONTH) == []
    assert client.calls == []


def test_merge_prompt_asks_for_rationale_before_decision():
    prompt = suggestions.SYSTEM_PROMPTS["merge"]
    format_line = next(line for line in prompt.splitlines() if '"same_product"' in line and '"rationale"' in line)
    assert format_line.index('"rationale"') < format_line.index('"same_product"')


def test_spent_this_month_reads_current_month(conn, monkeypatch):
    monkeypatch.setattr(suggestions, "_current_month", lambda: "2026-09")
    ai_usage.add_spent(conn, "2026-09", 0.42)
    assert suggestions.spent_this_month(conn) == pytest.approx(0.42)


def test_is_available_never_raises_on_broken_connection(conn, cfg):
    conn.close()
    assert suggestions.is_available(conn, cfg, MONTH) is False
