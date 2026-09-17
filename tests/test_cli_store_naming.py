"""`julius mercados revisar`, and the same naming running inside `julius importar`.

The network is never reached: `catalog.cnpj_client.fetch_trade_name` is replaced in every test,
and the AI is either absent or a scripted fake.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import copied_fixtures, restore_fixture
from _fakes import ScriptedLlmClient
from julius.cli import app
from julius.infra import cnpj_client
from julius.infra.llm_client import LlmResponse
from julius.services import catalog

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()

# qrcode-2.html is the Veneza (CNPJ 20209736000181); qrcode-5.html is the Assaí, whose CNPJ
# starts with a zero — the one value that must never pass through an int.
VENEZA_CNPJ = "20209736000181"
ASSAI_CNPJ = "06057223052643"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "prices.db"))
    monkeypatch.setenv("COLUMNS", "220")
    monkeypatch.setattr(sys.modules[__name__], "FIXTURES", copied_fixtures(tmp_path))
    # No store naming reaches the real registry unless a test says what it answers.
    monkeypatch.setattr(cnpj_client, "fetch_trade_name", lambda cnpj, **kw: None)
    monkeypatch.setattr(catalog.cnpj_client, "fetch_trade_name", lambda cnpj, **kw: None)


@pytest.fixture
def registry(monkeypatch):
    answers: dict[str, str] = {}
    monkeypatch.setattr(catalog.cnpj_client, "fetch_trade_name", lambda cnpj, **kw: answers.get(cnpj))
    return answers


def _with_ai(monkeypatch, *, trade_names: dict[int, str | None]) -> ScriptedLlmClient:
    payload = {"stores": [{"id": i, "trade_name": name} for i, name in trade_names.items()]}
    client = ScriptedLlmClient(by_kind={"store": LlmResponse(json.dumps(payload), 100, 20)})
    monkeypatch.setenv("JULIUS_AI_API_KEY", "secret")
    monkeypatch.setenv("JULIUS_AI_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("JULIUS_AI_MODEL", "cheap-1")
    monkeypatch.setenv("JULIUS_AI_INPUT_PRICE_USD_PER_1M", "1.0")
    monkeypatch.setenv("JULIUS_AI_OUTPUT_PRICE_USD_PER_1M", "1.0")
    monkeypatch.setattr("julius.infra.llm_client.HttpLlmClient.from_config", classmethod(lambda cls, cfg: client))
    return client


def _import(*names: str):
    result = runner.invoke(app, ["importar", *(str(restore_fixture(FIXTURES, name)) for name in names)])
    assert result.exit_code == 0, result.output
    return result


def _run(*args: str):
    return runner.invoke(app, list(args))


def _actions(tmp_path) -> list[dict]:
    path = tmp_path / "actions.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_revisar_with_no_stores_says_so():
    assert "Todos os mercados já têm apelido." in _run("mercados", "revisar").output


def test_revisar_uses_the_registry_name_and_the_receipt_place(registry):
    _import("qrcode-2.html")
    registry[VENEZA_CNPJ] = "SUPERMERCADO VENEZA"
    result = _run("mercados", "revisar")
    assert result.exit_code == 0
    assert "SUPERMERCADO VENEZA — GUARA II" in result.output
    assert "registro do CNPJ" in result.output
    assert "SUPERMERCADO VENEZA — GUARA II" in _run("mercados", "listar").output


def test_revisar_falls_back_to_the_ai_for_what_the_registry_leaves_empty(monkeypatch, registry):
    _import("qrcode-5.html")
    client = _with_ai(monkeypatch, trade_names={1: "Assaí Atacadista"})
    result = _run("mercados", "revisar")
    assert "Assaí Atacadista — St Complementares" in result.output
    assert "IA" in result.output
    assert len(client.calls) == 1


def test_the_place_alone_is_added_when_no_source_knows_the_name(registry):
    result = _import("qrcode-3.html")
    assert "DONA DE CASA S/A — GUARA II" in result.output
    assert "endereço do cupom" in result.output


def test_revisar_after_a_place_only_naming_reports_that_nothing_new_was_found(registry):
    _import("qrcode-3.html")
    result = _run("mercados", "revisar")
    assert "nenhuma fonte soube o nome" in result.output


def test_the_nickname_shows_up_in_consultar_which_is_where_the_complaint_was(registry):
    """The whole point: the name the user reads when looking a price up (RF8)."""
    registry[VENEZA_CNPJ] = "SUPERMERCADO VENEZA"
    _import("qrcode-2.html")
    result = _run("consultar", "contra file")
    assert "VENEZA" in result.output, result.output
    assert "COMERCIAL DE ALIMENTOS HTP" not in result.output


def test_a_nickname_typed_by_hand_survives_revisar(registry):
    _import("qrcode-2.html")
    _run("mercados", "renomear", VENEZA_CNPJ, "O do Guará")
    registry[VENEZA_CNPJ] = "SUPERMERCADO VENEZA"
    _run("mercados", "revisar")
    assert "O do Guará" in _run("mercados", "listar").output


def test_the_action_log_keeps_the_leading_zero_of_the_cnpj(tmp_path, monkeypatch, registry):
    """A CNPJ stored as an int loses its leading zero, and the undo command it prints would then
    match no store at all — the failure is silent, because the table renders it as text either way.
    """
    _import("qrcode-5.html")
    _with_ai(monkeypatch, trade_names={1: "Assaí Atacadista"})
    _run("mercados", "revisar")
    records = [r for r in _actions(tmp_path) if r.get("field") == "nickname"]
    # Two: the import named it from the place alone, then revisar upgraded it with the trade name.
    assert [r["after"] for r in records] == [
        "SENDAS DISTRIBUIDORA S/A — St Complementares",
        "Assaí Atacadista — St Complementares",
    ]
    assert all(r["product_id"] == ASSAI_CNPJ and r["product_id"].startswith("0") for r in records)
    assert records[0]["undo"] == f'julius mercados renomear {ASSAI_CNPJ} "SENDAS DISTRIBUIDORA S/A"'


def test_the_undo_command_from_the_log_actually_restores_the_old_nickname(tmp_path, registry):
    _import("qrcode-2.html")
    registry[VENEZA_CNPJ] = "SUPERMERCADO VENEZA"
    _run("mercados", "revisar")
    record = [r for r in _actions(tmp_path) if r.get("field") == "nickname"][0]
    assert _run("mercados", "renomear", record["product_id"], record["before"]).exit_code == 0
    assert "COMERCIAL DE ALIMENTOS HTP LTDA" in _run("mercados", "listar").output


def test_produtos_revisar_ultimas_acoes_lists_the_nickname_change(registry):
    _import("qrcode-2.html")
    registry[VENEZA_CNPJ] = "SUPERMERCADO VENEZA"
    _run("mercados", "revisar")
    result = _run("produtos", "revisar", "--ultimas-acoes")
    assert "nickname" in result.output
    assert VENEZA_CNPJ in result.output


def test_importar_names_the_store_it_just_created(registry):
    registry[VENEZA_CNPJ] = "SUPERMERCADO VENEZA"
    result = _import("qrcode-2.html")
    assert "ganharam apelido" in result.output
    assert "SUPERMERCADO VENEZA — GUARA II" in result.output


def test_importar_still_succeeds_when_the_registry_lookup_explodes(monkeypatch):
    def boom(cnpj, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(catalog.cnpj_client, "fetch_trade_name", boom)
    result = _import("qrcode-2.html")
    assert result.exit_code == 0
    assert "1 itens novos" in result.output


def test_the_rename_hint_stops_nagging_once_the_store_is_named(registry):
    registry[VENEZA_CNPJ] = "SUPERMERCADO VENEZA"
    result = _import("qrcode-2.html")
    assert "ainda com a razão social" not in result.output


def test_a_provisional_place_only_name_is_upgraded_on_the_next_pass(registry):
    """A registry that was merely unreachable must not cost the trade name for good."""
    result = _import("qrcode-2.html")
    assert "COMERCIAL DE ALIMENTOS HTP LTDA — GUARA II" in result.output
    registry[VENEZA_CNPJ] = "SUPERMERCADO VENEZA"
    assert "SUPERMERCADO VENEZA — GUARA II" in _run("mercados", "revisar").output


def test_a_second_pass_that_changes_nothing_logs_nothing(tmp_path, registry):
    """The store stays pending on purpose, so the registry is consulted again — but an unchanged
    nickname must not add a line to actions.jsonl, or the audit fills up with no-ops."""
    _import("qrcode-3.html")
    before = len(_actions(tmp_path))
    assert before == 1
    assert _run("mercados", "revisar").exit_code == 0
    assert len(_actions(tmp_path)) == before


def test_the_rename_hint_still_fires_for_a_store_only_the_place_could_name(registry):
    """A place-only nickname carries the legal name, so the nudge to rename has to survive it."""
    result = _import("qrcode-3.html")
    assert "DONA DE CASA S/A — GUARA II" in result.output
    assert "razão social" in result.output
