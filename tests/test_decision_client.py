import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from julius import config
from julius.config import Config
from julius.infra import decision_client
from julius.infra.decision_client import ChoiceResult, NoulResult, TypeSafeDecisionClient

GOOD_NOUL_PAYLOAD = {
    "answers": {"q": {"type": "noul", "noul": 0.02}},
    "usage": {"input_tokens": 40, "output_tokens": 5},
}

GOOD_CHOICE_PAYLOAD = {
    "answers": {
        "q": {
            "type": "choice",
            "choice": "weight",
            "confidence": 0.8,
            "probabilities": {"weight": 0.9, "unit": 0.1},
        }
    },
    "usage": {"input_tokens": 30, "output_tokens": 4},
}


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def client():
    return TypeSafeDecisionClient("https://api.example/v1/systemone", "secret-key", "jev-latest", timeout_seconds=7)


def _fake_urlopen(monkeypatch, response=None, error=None):
    calls = []

    def fake(request, timeout=None):
        calls.append((request, timeout))
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(decision_client, "urlopen", fake)
    return calls


def test_ask_noul_parses_value_and_tokens(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse(GOOD_NOUL_PAYLOAD))
    assert client.ask_noul("A vs B", "same product?") == NoulResult(0.02, 40, 5)


def test_ask_noul_body_and_headers(client, monkeypatch):
    calls = _fake_urlopen(monkeypatch, FakeResponse(GOOD_NOUL_PAYLOAD))
    client.ask_noul("A vs B", "same product?")
    request, timeout = calls[0]
    assert request.full_url == "https://api.example/v1/systemone"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert request.get_header("Content-type") == "application/json"
    body = json.loads(request.data)
    assert body["model"] == "jev-latest"
    assert body["state"] == "A vs B"
    assert body["questions"] == {"q": {"type": "noul", "instructions": "same product?"}}
    assert timeout == 7


def test_ask_choice_parses_choice_confidence_and_probabilities(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse(GOOD_CHOICE_PAYLOAD))
    result = client.ask_choice("some product", "pick a form", {"weight": "sold loose", "unit": "sold as-is"})
    assert result == ChoiceResult("weight", 0.8, {"weight": 0.9, "unit": 0.1}, 30, 4)


def test_ask_choice_sends_criteria(client, monkeypatch):
    calls = _fake_urlopen(monkeypatch, FakeResponse(GOOD_CHOICE_PAYLOAD))
    client.ask_choice("some product", "pick a form", {"weight": "sold loose"})
    body = json.loads(calls[0][0].data)
    assert body["questions"]["q"] == {
        "type": "choice",
        "instructions": "pick a form",
        "criteria": {"weight": "sold loose"},
    }


def test_http_error_maps_to_http_code(client, monkeypatch):
    _fake_urlopen(monkeypatch, error=HTTPError("u", 500, "boom", {}, None))
    assert client.ask_noul("a", "b") == NoulResult(None, error="HTTP 500")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError(), "timeout"),
        (URLError("dns down"), "network:"),
    ],
)
def test_timeout_and_network_errors(client, monkeypatch, error, expected):
    _fake_urlopen(monkeypatch, error=error)
    result = client.ask_noul("a", "b")
    assert result.value is None
    assert result.error == expected or result.error.startswith(expected)


def test_non_2xx_status_without_exception(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse(GOOD_NOUL_PAYLOAD, status=429))
    assert client.ask_noul("a", "b") == NoulResult(None, error="HTTP 429")


def test_invalid_json_body(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse(b"<html>not json"))
    assert client.ask_noul("a", "b") == NoulResult(None, error="invalid json body")


def test_missing_answer_is_invalid_response_shape(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"answers": {}, "usage": {"input_tokens": 1, "output_tokens": 1}}))
    result = client.ask_noul("a", "b")
    assert result.error == "invalid response shape"
    assert (result.input_tokens, result.output_tokens) == (1, 1)


def test_noul_value_wrong_type_is_invalid_response_shape(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"answers": {"q": {"noul": "high"}}, "usage": {}}))
    assert client.ask_noul("a", "b").error == "invalid response shape"


def test_choice_missing_choice_is_invalid_response_shape(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"answers": {"q": {"confidence": 0.5}}, "usage": {}}))
    result = client.ask_choice("a", "b", {"x": "y"})
    assert result == ChoiceResult(None, None, None, error="invalid response shape")


def test_choice_without_confidence_or_probabilities_defaults_to_none(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"answers": {"q": {"choice": "unit"}}, "usage": {}}))
    result = client.ask_choice("a", "b", {"unit": "x"})
    assert result == ChoiceResult("unit", None, None, 0, 0)


def test_unexpected_exception_never_propagates(client, monkeypatch):
    _fake_urlopen(monkeypatch, error=RuntimeError("unexpected"))
    assert client.ask_noul("a", "b") == NoulResult(None, error="RuntimeError: unexpected")


def test_from_config_returns_none_when_not_configured():
    assert TypeSafeDecisionClient.from_config(config.load({})) is None


def test_from_config_builds_client_when_key_present():
    cfg = Config(
        db_path=Path("/tmp/x.db"),
        ai_api_key=None,
        ai_base_url=None,
        ai_model=None,
        ai_budget_usd=1.0,
        ai_input_price_usd_per_1m=None,
        ai_output_price_usd_per_1m=None,
        typesafe_api_key="k",
    )
    built = TypeSafeDecisionClient.from_config(cfg)
    assert isinstance(built, TypeSafeDecisionClient)
    assert built._url == "https://api.typesafe.ai/v1/systemone"
    assert built._model == "jev-latest"
