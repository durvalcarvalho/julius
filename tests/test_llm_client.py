import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from julius import config
from julius.config import Config
from julius.infra import llm_client
from julius.infra.llm_client import HttpLlmClient, LlmResponse

GOOD_PAYLOAD = {
    "choices": [{"message": {"role": "assistant", "content": "hello"}}],
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
    assert client.complete("sys", "usr") == LlmResponse("hello", 12, 3)


def test_complete_sends_expected_url_headers_and_body(client, monkeypatch):
    calls = _fake_urlopen(monkeypatch, FakeResponse(GOOD_PAYLOAD))
    client.complete("be terse", "is 12 expensive?")
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
    assert timeout == 7


def test_base_url_without_trailing_slash_gives_same_url(monkeypatch):
    calls = _fake_urlopen(monkeypatch, FakeResponse(GOOD_PAYLOAD))
    HttpLlmClient("https://api.example/v1", "k", "m").complete("a", "b")
    assert calls[0][0].full_url == "https://api.example/v1/chat/completions"


def test_http_error_returns_none(client, monkeypatch):
    _fake_urlopen(monkeypatch, error=HTTPError("u", 500, "boom", {}, None))
    assert client.complete("a", "b") is None


def test_network_error_returns_none(client, monkeypatch):
    _fake_urlopen(monkeypatch, error=URLError("dns down"))
    assert client.complete("a", "b") is None


def test_non_2xx_status_returns_none(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse(GOOD_PAYLOAD, status=429))
    assert client.complete("a", "b") is None


def test_invalid_json_returns_none(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse(b"<html>not json"))
    assert client.complete("a", "b") is None


def test_missing_usage_returns_none(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"choices": GOOD_PAYLOAD["choices"]}))
    assert client.complete("a", "b") is None


def test_missing_choices_returns_none(client, monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"usage": GOOD_PAYLOAD["usage"]}))
    assert client.complete("a", "b") is None


def test_non_string_content_returns_none(client, monkeypatch):
    payload = {**GOOD_PAYLOAD, "choices": [{"message": {"content": None}}]}
    _fake_urlopen(monkeypatch, FakeResponse(payload))
    assert client.complete("a", "b") is None


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


def test_complete_never_raises_even_on_unexpected_exception(client, monkeypatch):
    _fake_urlopen(monkeypatch, error=RuntimeError("unexpected"))
    assert client.complete("a", "b") is None
