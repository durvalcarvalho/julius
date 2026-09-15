from dataclasses import replace
from pathlib import Path

import pytest

from julius.config import Config
from julius.domain.models import ContentSuggestion, MergeSuggestion
from julius.infra.llm_client import LlmResponse
from julius.repositories import ai_usage
from julius.services import suggestions

MONTH = "2026-09"
CONFIG = Config(
    db_path=Path("unused.db"),
    ai_api_key="secret",
    ai_base_url="https://api.example/v1",
    ai_model="cheap-1",
    ai_budget_usd=1.0,
    ai_input_price_usd_per_1m=1.0,
    ai_output_price_usd_per_1m=1.0,
)


class FakeLlmClient:
    def __init__(self, text: str | None, input_tokens: int = 1000, output_tokens: int = 500) -> None:
        self._response = None if text is None else LlmResponse(text, input_tokens, output_tokens)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> LlmResponse | None:
        self.calls.append((system_prompt, user_prompt))
        return self._response


class RaisingLlmClient:
    def complete(self, system_prompt: str, user_prompt: str) -> LlmResponse | None:
        raise RuntimeError("boom")


MERGE_JSON = '{"same_product": true, "confidence": 0.9, "rationale": "mesma marca e tamanho"}'


def test_unavailable_without_api_key_and_client_not_called(conn):
    client = FakeLlmClient(MERGE_JSON)
    config = replace(CONFIG, ai_api_key=None)
    assert suggestions.is_available(conn, config, MONTH) is False
    assert suggestions.suggest_merge(conn, config, client, "A", "B", MONTH) is None
    assert client.calls == []


def test_unavailable_without_token_prices(conn):
    assert suggestions.is_available(conn, replace(CONFIG, ai_input_price_usd_per_1m=None), MONTH) is False
    assert suggestions.is_available(conn, replace(CONFIG, ai_output_price_usd_per_1m=None), MONTH) is False


def test_unavailable_when_budget_reached(conn):
    ai_usage.add_spent(conn, MONTH, 1.0)
    client = FakeLlmClient(MERGE_JSON)
    assert suggestions.is_available(conn, CONFIG, MONTH) is False
    assert suggestions.suggest_merge(conn, CONFIG, client, "A", "B", MONTH) is None
    assert client.calls == []


def test_suggest_merge_parses_json_and_records_cost(conn):
    client = FakeLlmClient(MERGE_JSON, input_tokens=1000, output_tokens=500)
    result = suggestions.suggest_merge(conn, CONFIG, client, "PICANHA BOV FAT kg PROMO", "PICANHA BOV FAT kg", MONTH)
    assert result == MergeSuggestion(same_product=True, confidence=0.9, rationale="mesma marca e tamanho")
    assert ai_usage.spent_in_month(conn, MONTH) == pytest.approx(0.0015)
    assert len(client.calls) == 1
    assert "PICANHA BOV FAT kg PROMO" in client.calls[0][1]


def test_suggest_merge_tolerates_code_fences(conn):
    client = FakeLlmClient(f"Claro! Aqui está:\n```json\n{MERGE_JSON}\n```\n")
    result = suggestions.suggest_merge(conn, CONFIG, client, "A", "B", MONTH)
    assert result is not None and result.same_product is True


def test_malformed_json_returns_none_but_cost_is_recorded(conn):
    client = FakeLlmClient("não sei dizer", input_tokens=1000, output_tokens=500)
    assert suggestions.suggest_merge(conn, CONFIG, client, "A", "B", MONTH) is None
    assert ai_usage.spent_in_month(conn, MONTH) == pytest.approx(0.0015)


def test_client_none_returns_none_and_nothing_recorded(conn):
    client = FakeLlmClient(None)
    assert suggestions.suggest_merge(conn, CONFIG, client, "A", "B", MONTH) is None
    assert suggestions.suggest_content(conn, CONFIG, client, "A", MONTH) is None
    assert suggestions.suggest_tags(conn, CONFIG, client, "A", [], MONTH) == []
    assert ai_usage.spent_in_month(conn, MONTH) == 0.0


@pytest.mark.parametrize(
    "text",
    [
        '{"quantity": 500, "unit": "G", "confidence": 0.9}',
        '{"quantity": 0, "unit": "KG", "confidence": 0.9}',
        '{"quantity": -1, "unit": "L", "confidence": 0.9}',
        '{"quantity": "muito", "unit": "L", "confidence": 0.9}',
    ],
)
def test_suggest_content_rejects_bad_unit_and_non_positive(conn, text):
    assert suggestions.suggest_content(conn, CONFIG, FakeLlmClient(text), "X", MONTH) is None


def test_suggest_content_accepts_valid_payload(conn):
    client = FakeLlmClient('{"quantity": 1.5, "unit": "l", "confidence": 0.8}')
    result = suggestions.suggest_content(conn, CONFIG, client, "REFRI ANT GUARANA PET 1.5L", MONTH)
    assert result == ContentSuggestion(quantity=1.5, unit="L", confidence=0.8)


def test_suggest_tags_normalizes_dedups_and_caps_at_three(conn):
    client = FakeLlmClient('[" Limpeza ", "limpeza", "", "cozinha", "HIGIENE", "extra"]')
    assert suggestions.suggest_tags(conn, CONFIG, client, "DESENGORD UAU 500ML", ["limpeza"], MONTH) == [
        "limpeza",
        "cozinha",
        "higiene",
    ]
    assert "limpeza" in client.calls[0][1]


def test_suggest_tags_non_list_payload_returns_empty(conn):
    assert suggestions.suggest_tags(conn, CONFIG, FakeLlmClient('{"tag": "x"}'), "X", [], MONTH) == []


def test_functions_never_raise_when_client_raises(conn):
    client = RaisingLlmClient()
    assert suggestions.suggest_merge(conn, CONFIG, client, "A", "B", MONTH) is None
    assert suggestions.suggest_content(conn, CONFIG, client, "A", MONTH) is None
    assert suggestions.suggest_tags(conn, CONFIG, client, "A", [], MONTH) == []
    assert ai_usage.spent_in_month(conn, MONTH) == 0.0


def test_is_available_never_raises_on_broken_connection(conn):
    conn.close()
    assert suggestions.is_available(conn, CONFIG, MONTH) is False
