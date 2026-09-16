import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from julius import config
from julius.config import Config
from julius.infra import llm_client
from julius.infra.llm_client import HttpLlmClient, LlmResponse

GOOD_PAYLOAD = {
    "choices": [{"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
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
    return HttpLlmClient("https://api.example/v1/", "secret-key", "cheap-1", timeout_seconds=7)


def _fake_urlopen(monkeypatch, response=None, error=None):
    calls = []

    def fake(request, timeout=None):
        calls.append((request, timeout))
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(llm_client, "urlopen", fake)
    return calls


def test_complete_parses_text_and_token_counts(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse(GOOD_PAYLOAD))
    assert client.complete("sys", "usr", max_tokens=100) == LlmResponse("hello", 12, 3)


def test_body_has_json_mode_max_tokens_temperature_and_messages(client, monkeypatch):
    calls = _fake_urlopen(monkeypatch, FakeResponse(GOOD_PAYLOAD))
    client.complete("be terse", "is 12 expensive?", max_tokens=250)
    request, timeout = calls[0]
    assert request.full_url == "https://api.example/v1/chat/completions"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert request.get_header("Content-type") == "application/json"
    body = json.loads(request.data)
    assert body["model"] == "cheap-1"
    assert body["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "is 12 expensive?"},
    ]
    assert body["temperature"] == 0
    assert body["max_tokens"] == 250
    assert body["response_format"] == {"type": "json_object"}
    assert timeout == 7


def test_request_extras_are_merged_into_body_and_can_override(monkeypatch):
    calls = _fake_urlopen(monkeypatch, FakeResponse(GOOD_PAYLOAD))
    client = HttpLlmClient(
        "https://api.example/v1",
        "k",
        "m",
        request_extras={"thinking": {"type": "disabled"}, "temperature": 0.2},
    )
    client.complete("a", "b", max_tokens=10)
    body = json.loads(calls[0][0].data)
    assert body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == 0.2


def test_from_config_passes_request_extras(monkeypatch):
    calls = _fake_urlopen(monkeypatch, FakeResponse(GOOD_PAYLOAD))
    cfg = config.load(
        {
            "JULIUS_AI_API_KEY": "k",
            "JULIUS_AI_BASE_URL": "https://api.example/v1",
            "JULIUS_AI_MODEL": "cheap-1",
            "JULIUS_AI_REQUEST_EXTRAS": '{"thinking":{"type":"disabled"}}',
        }
    )
    HttpLlmClient.from_config(cfg).complete("a", "b", max_tokens=10)
    body = json.loads(calls[0][0].data)
    assert body["thinking"] == {"type": "disabled"}


def test_http_error_maps_to_http_code(client, monkeypatch):
    _fake_urlopen(monkeypatch, error=HTTPError("u", 500, "boom", {}, None))
    assert client.complete("a", "b", max_tokens=10) == LlmResponse("", 0, 0, error="HTTP 500")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError(), "timeout"),
        (URLError("dns down"), "network:"),
    ],
)
def test_timeout_and_network_errors(client, monkeypatch, error, expected):
    _fake_urlopen(monkeypatch, error=error)
    result = client.complete("a", "b", max_tokens=10)
    assert result.text == "" and result.input_tokens == 0 and result.output_tokens == 0
    assert result.error == expected or result.error.startswith(expected)


def test_non_2xx_status_without_exception(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse(GOOD_PAYLOAD, status=429))
    assert client.complete("a", "b", max_tokens=10) == LlmResponse("", 0, 0, error="HTTP 429")


def test_invalid_json_body(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse(b"<html>not json"))
    assert client.complete("a", "b", max_tokens=10) == LlmResponse("", 0, 0, error="invalid json body")


def test_finish_reason_length_is_error_but_keeps_tokens(client, monkeypatch):
    payload = {
        "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 1200},
    }
    _fake_urlopen(monkeypatch, FakeResponse(payload))
    result = client.complete("a", "b", max_tokens=1200)
    assert result.error == "finish_reason length"
    assert result.input_tokens == 1200
    assert result.output_tokens == 1200
    assert result.text == ""


@pytest.mark.parametrize("content", [None, "   "])
def test_empty_content_is_error_with_tokens(client, monkeypatch, content):
    payload = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1},
    }
    _fake_urlopen(monkeypatch, FakeResponse(payload))
    result = client.complete("a", "b", max_tokens=10)
    assert result.error == "empty content"
    assert (result.input_tokens, result.output_tokens) == (5, 1)


def test_missing_usage_and_missing_choices(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"choices": GOOD_PAYLOAD["choices"]}))
    assert client.complete("a", "b", max_tokens=10) == LlmResponse("", 0, 0, error="no usage")

    _fake_urlopen(monkeypatch, FakeResponse({"usage": GOOD_PAYLOAD["usage"]}))
    result = client.complete("a", "b", max_tokens=10)
    assert result.error == "no choices"
    assert (result.input_tokens, result.output_tokens) == (12, 3)


def test_unexpected_exception_never_propagates(client, monkeypatch):
    _fake_urlopen(monkeypatch, error=RuntimeError("unexpected"))
    assert client.complete("a", "b", max_tokens=10) == LlmResponse("", 0, 0, error="RuntimeError: unexpected")


def test_from_config_returns_none_when_not_configured():
    assert HttpLlmClient.from_config(config.load({})) is None
    assert HttpLlmClient.from_config(config.load({"JULIUS_AI_API_KEY": "k"})) is None


def test_from_config_builds_client_when_configured():
    cfg = Config(
        db_path=Path("/tmp/x.db"),
        ai_api_key="k",
        ai_base_url="https://api.example/v1",
        ai_model="cheap-1",
        ai_budget_usd=1.0,
        ai_input_price_usd_per_1m=None,
        ai_output_price_usd_per_1m=None,
    )
    built = HttpLlmClient.from_config(cfg)
    assert isinstance(built, HttpLlmClient)
    assert built._url == "https://api.example/v1/chat/completions"


def test_base_url_without_trailing_slash_gives_same_url(monkeypatch):
    calls = _fake_urlopen(monkeypatch, FakeResponse(GOOD_PAYLOAD))
    HttpLlmClient("https://api.example/v1", "k", "m").complete("a", "b", max_tokens=10)
    assert calls[0][0].full_url == "https://api.example/v1/chat/completions"
