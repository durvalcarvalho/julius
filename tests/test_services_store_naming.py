"""Store nicknames that already read like something a human recognises.

The two sources are complementary and measured that way (docs/requirements/
store-branch-nickname.md §7.5): the CNPJ registry knows the local store nobody outside the
neighbourhood has heard of, the model knows the national chain whose branch never declared a
trade name. These tests pin the ordering and, above all, the refusal: a store no source knows
must keep its legal name rather than receive a guess.
"""

from __future__ import annotations

import json

import pytest

from _fakes import RaisingLlmClient, ScriptedLlmClient
from julius.config import Config
from julius.domain.normalization import store_place
from julius.infra.llm_client import LlmResponse
from julius.repositories import stores as stores_repo
from julius.services import catalog

ASSAI = ("06057223052643", "SENDAS DISTRIBUIDORA S/A", "Q SMAS Trecho 03, 0, , St Complementares, Brasilia, DF")
VENEZA = ("20209736000181", "COMERCIAL DE ALIMENTOS HTP LTDA", "Q. QE 15 LOTE A, 0, , GUARA II, BRASILIA, DF")
CANDANGO = ("11832478000366", "DONA DE CASA S/A", "QUADRA QR 5, 05 MU 05, , CANDANGOLANDIA, BRASILIA, DF")


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


def _seed(conn, *entries) -> None:
    with conn:
        for cnpj, legal_name, address in entries:
            stores_repo.ensure_store(conn, cnpj, legal_name, address)


def _trade_response(names: dict[int, str | None]) -> LlmResponse:
    payload = {"stores": [{"id": index, "trade_name": name} for index, name in names.items()]}
    return LlmResponse(json.dumps(payload), 100, 20)


def _nickname(conn, cnpj: str) -> str:
    store = stores_repo.get_store(conn, cnpj)
    assert store is not None
    return store.nickname


# --- the place segment, measured on all five real addresses -------------------------------


@pytest.mark.parametrize(
    "address, expected",
    [
        ("Q. QE 15 LOTE A, 0, , GUARA II, BRASILIA, DF", "GUARA II"),
        ("QUADRA QE 30, 02/39, LJS 02/39, GUARA II, BRASILIA, DF", "GUARA II"),
        ("QUADRA QR 5, 05 MU 05, , CANDANGOLANDIA, BRASILIA, DF", "CANDANGOLANDIA"),
        ("Q SMAS Trecho 03, 0, , St Complementares, Brasilia, DF", "St Complementares"),
        ("A ADE CONJUNTO 31 LOTE 01 SALA 1, S /N, LOTE 01, AGUAS CLARAS, BRASILIA, DF", "AGUAS CLARAS"),
    ],
)
def test_store_place_reads_the_neighbourhood_of_every_real_address(address, expected):
    assert store_place(address) == expected


@pytest.mark.parametrize("address", [None, "", "SEM VIRGULA", "APENAS, DUAS", "A, , "])
def test_store_place_gives_up_quietly_when_there_is_no_neighbourhood(address):
    assert store_place(address) in (None, "A")


def test_store_place_is_right_anchored_so_a_comma_in_the_street_name_does_not_shift_it():
    # A left-anchored index would read "LOTE 01" here; the neighbourhood is the third from the end.
    assert store_place("A ADE CONJUNTO 31, S /N, LOTE 01, AGUAS CLARAS, BRASILIA, DF") == "AGUAS CLARAS"


# --- the registry covers the store nobody outside the bairro knows -------------------------


def test_registry_trade_name_plus_place_becomes_the_nickname(conn, cfg):
    _seed(conn, VENEZA)
    applied = catalog.name_stores(conn, cfg, None, fetch_trade_name=lambda cnpj: "SUPERMERCADO VENEZA")
    assert [(a.cnpj, a.after, a.source) for a in applied] == [
        (VENEZA[0], "SUPERMERCADO VENEZA — GUARA II", "registry")
    ]
    assert _nickname(conn, VENEZA[0]) == "SUPERMERCADO VENEZA — GUARA II"


def test_the_model_is_never_asked_about_a_store_the_registry_already_named(conn, cfg):
    _seed(conn, VENEZA)
    client = ScriptedLlmClient(by_kind={"store": _trade_response({1: "Errado"})})
    catalog.name_stores(conn, cfg, client, fetch_trade_name=lambda cnpj: "SUPERMERCADO VENEZA")
    assert client.calls == []


# --- the model covers the chain whose branch declared nothing ------------------------------


def test_the_model_fills_what_the_registry_left_empty(conn, cfg):
    _seed(conn, ASSAI)
    client = ScriptedLlmClient(by_kind={"store": _trade_response({1: "Assaí Atacadista"})})
    applied = catalog.name_stores(conn, cfg, client, fetch_trade_name=lambda cnpj: None)
    assert [(a.after, a.source) for a in applied] == [("Assaí Atacadista — St Complementares", "ai")]
    assert len(client.calls) == 1


def test_both_sources_are_used_in_one_pass_and_each_covers_what_the_other_misses(conn, cfg):
    _seed(conn, ASSAI, VENEZA)
    registry = {VENEZA[0]: "SUPERMERCADO VENEZA", ASSAI[0]: None}
    client = ScriptedLlmClient(by_kind={"store": _trade_response({1: "Assaí Atacadista"})})
    applied = catalog.name_stores(conn, cfg, client, fetch_trade_name=registry.get)
    by_cnpj = {a.cnpj: a for a in applied}
    assert by_cnpj[VENEZA[0]].source == "registry"
    assert by_cnpj[ASSAI[0]].source == "ai"
    assert _nickname(conn, ASSAI[0]) == "Assaí Atacadista — St Complementares"


# --- refusal: no source knows, so nothing is invented --------------------------------------


def test_a_store_no_source_knows_keeps_its_legal_name_but_still_gains_the_place(conn, cfg):
    _seed(conn, CANDANGO)
    client = ScriptedLlmClient(by_kind={"store": _trade_response({1: None})})
    applied = catalog.name_stores(conn, cfg, client, fetch_trade_name=lambda cnpj: None)
    assert [(a.after, a.source) for a in applied] == [("DONA DE CASA S/A — CANDANGOLANDIA", "place")]


def test_with_neither_trade_name_nor_address_the_store_is_left_completely_alone(conn, cfg):
    _seed(conn, ("11832478000285", "DONA DE CASA S/A", None))
    client = ScriptedLlmClient(by_kind={"store": _trade_response({1: None})})
    assert catalog.name_stores(conn, cfg, client, fetch_trade_name=lambda cnpj: None) == []
    assert _nickname(conn, "11832478000285") == "DONA DE CASA S/A"


# --- a nickname the user typed is untouchable ----------------------------------------------


def test_a_nickname_typed_by_hand_is_never_a_candidate(conn, cfg):
    _seed(conn, VENEZA)
    catalog.rename_store(conn, VENEZA[0], "O do Guará")
    applied = catalog.name_stores(conn, cfg, None, fetch_trade_name=lambda cnpj: "SUPERMERCADO VENEZA")
    assert applied == []
    assert _nickname(conn, VENEZA[0]) == "O do Guará"


def test_naming_twice_is_a_no_op_because_the_store_stops_being_unnamed(conn, cfg):
    _seed(conn, VENEZA)
    fetch = lambda cnpj: "SUPERMERCADO VENEZA"  # noqa: E731
    assert len(catalog.name_stores(conn, cfg, None, fetch_trade_name=fetch)) == 1
    assert catalog.name_stores(conn, cfg, None, fetch_trade_name=fetch) == []


# --- failures never break the caller -------------------------------------------------------


def test_a_registry_lookup_that_raises_falls_back_to_the_place_alone(conn, cfg):
    _seed(conn, CANDANGO)

    def boom(cnpj: str) -> str | None:
        raise RuntimeError("network down")

    applied = catalog.name_stores(conn, cfg, None, fetch_trade_name=boom)
    assert [a.after for a in applied] == ["DONA DE CASA S/A — CANDANGOLANDIA"]


def test_a_model_that_raises_falls_back_to_the_place_alone(conn, cfg):
    _seed(conn, CANDANGO)
    applied = catalog.name_stores(conn, cfg, RaisingLlmClient(), fetch_trade_name=lambda cnpj: None)
    assert [(a.after, a.source) for a in applied] == [("DONA DE CASA S/A — CANDANGOLANDIA", "place")]


def test_without_ai_configured_the_registry_still_works_alone(conn, db_path):
    _seed(conn, VENEZA)
    bare = Config(
        db_path=db_path,
        ai_api_key=None,
        ai_base_url=None,
        ai_model=None,
        ai_budget_usd=1.0,
        ai_input_price_usd_per_1m=None,
        ai_output_price_usd_per_1m=None,
    )
    applied = catalog.name_stores(conn, bare, None, fetch_trade_name=lambda cnpj: "SUPERMERCADO VENEZA")
    assert [a.source for a in applied] == ["registry"]


def test_cnpjs_narrows_the_pass_to_the_stores_asked_for(conn, cfg):
    _seed(conn, ASSAI, VENEZA)
    applied = catalog.name_stores(
        conn, cfg, None, cnpjs=[VENEZA[0]], fetch_trade_name=lambda cnpj: "SUPERMERCADO VENEZA"
    )
    assert [a.cnpj for a in applied] == [VENEZA[0]]
    assert _nickname(conn, ASSAI[0]) == ASSAI[1]
