"""The CNPJ registry lookup. Never hits the network: `urlopen` is always replaced.

An empty `nome_fantasia` is a normal answer, not a failure — the field is declaratory and
optional, and it is measurably empty for the Assaí (docs/requirements/store-branch-nickname.md
§7.1). Every failure mode has to read the same way as that empty answer, because the caller's
fallback is identical either way: keep the legal name and let the rename hint offer it again.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest

from julius.infra import cnpj_client
from julius.infra.cnpj_client import fetch_trade_name


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


def _fake_urlopen(monkeypatch, response=None, error=None):
    calls = []

    def fake(request, timeout=None):
        calls.append((request, timeout))
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(cnpj_client, "urlopen", fake)
    return calls


def test_returns_the_trade_name_on_record(monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"nome_fantasia": "SUPERMERCADO VENEZA"}))
    assert fetch_trade_name("20209736000181") == "SUPERMERCADO VENEZA"


def test_requests_the_cnpj_as_given_without_reformatting_it(monkeypatch):
    calls = _fake_urlopen(monkeypatch, FakeResponse({"nome_fantasia": "X"}))
    fetch_trade_name("06057223052643", timeout_seconds=3)
    request, timeout = calls[0]
    # The leading zero has to survive: it is a string all the way through, never an int.
    assert request.full_url.endswith("/06057223052643")
    assert request.get_method() == "GET"
    assert timeout == 3


def test_keeps_the_registry_casing_verbatim(monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"nome_fantasia": "COSTA ATACADAO"}))
    assert fetch_trade_name("27289076001379") == "COSTA ATACADAO"


@pytest.mark.parametrize("value", ["", "   ", None, 42, [], {}])
def test_an_absent_or_unusable_trade_name_reads_as_none(monkeypatch, value):
    _fake_urlopen(monkeypatch, FakeResponse({"nome_fantasia": value}))
    assert fetch_trade_name("06057223052643") is None


def test_a_payload_without_the_field_reads_as_none(monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"razao_social": "SENDAS DISTRIBUIDORA S/A"}))
    assert fetch_trade_name("06057223052643") is None


@pytest.mark.parametrize(
    "error",
    [
        URLError("no route to host"),
        HTTPError("https://example", 429, "Too Many Requests", {}, None),
        HTTPError("https://example", 500, "Server Error", {}, None),
        TimeoutError("timed out"),
        OSError("socket blew up"),
    ],
)
def test_every_transport_failure_reads_as_none(monkeypatch, error):
    _fake_urlopen(monkeypatch, error=error)
    assert fetch_trade_name("20209736000181") is None


def test_a_non_2xx_status_reads_as_none(monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse({"nome_fantasia": "NAO USE"}, status=404))
    assert fetch_trade_name("20209736000181") is None


def test_a_body_that_is_not_json_reads_as_none(monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse(b"<html>rate limited</html>"))
    assert fetch_trade_name("20209736000181") is None


def test_a_json_body_that_is_not_an_object_reads_as_none(monkeypatch):
    _fake_urlopen(monkeypatch, FakeResponse([{"nome_fantasia": "X"}]))
    assert fetch_trade_name("20209736000181") is None
