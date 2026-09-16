"""End-to-end flows through the CLI, the way a user would run them."""

import csv
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

import julius.cli.products as products_cli
import julius.cli.receipts as receipts_cli
from _fakes import ScriptedLlmClient
from julius.cli import app
from julius.infra import db
from julius.infra.llm_client import LlmResponse
from julius.services import catalog, importing
from julius.services.search import search_prices
from julius.parsers.df import DFReceiptParser

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JULIUS_DB", str(tmp_path / "prices.db"))
    monkeypatch.setenv("COLUMNS", "200")
    for name in (
        "JULIUS_AI_API_KEY",
        "JULIUS_AI_BASE_URL",
        "JULIUS_AI_MODEL",
        "JULIUS_AI_BUDGET_USD",
        "JULIUS_AI_INPUT_PRICE_USD_PER_1M",
        "JULIUS_AI_OUTPUT_PRICE_USD_PER_1M",
    ):
        monkeypatch.delenv(name, raising=False)


def _run(*args: str, **kwargs):
    return runner.invoke(app, list(args), **kwargs)


def _import(*names: str):
    result = _run("importar", *(str(FIXTURES / name) for name in names))
    assert result.exit_code == 0, result.output
    return result


def _product_id(name: str) -> int:
    output = _run("produtos", "listar").output
    match = re.search(r"│\s*(\d+)\s*│\s*" + re.escape(name) + r"\s*│", output)
    assert match, f"{name!r} not found in:\n{output}"
    return int(match.group(1))


def _row_containing(output: str, needle: str) -> str:
    rows = [line for line in output.splitlines() if needle in line]
    assert len(rows) == 1, f"expected one row with {needle!r}, got {rows}"
    return rows[0]


def _ai_env(monkeypatch, **extra):
    monkeypatch.setenv("JULIUS_AI_API_KEY", "k")
    monkeypatch.setenv("JULIUS_AI_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("JULIUS_AI_MODEL", "cheap-1")
    monkeypatch.setenv("JULIUS_AI_INPUT_PRICE_USD_PER_1M", "1.0")
    monkeypatch.setenv("JULIUS_AI_OUTPUT_PRICE_USD_PER_1M", "1.0")
    monkeypatch.setenv("JULIUS_AI_BUDGET_USD", "5.0")
    for name, value in extra.items():
        monkeypatch.setenv(name, value)


def _stub_client(monkeypatch, client):
    class Stub:
        @staticmethod
        def from_config(config):
            return client

    monkeypatch.setattr(receipts_cli, "HttpLlmClient", Stub)
    monkeypatch.setattr(products_cli, "HttpLlmClient", Stub)


def _enrich(items: list[dict]) -> LlmResponse:
    return LlmResponse(json.dumps({"products": items}), 1000, 500)


def _match(ids: list[int]) -> LlmResponse:
    return LlmResponse(json.dumps({"ids": ids}), 10, 5)


def _export_rows(tmp_path: Path) -> list[dict[str, str]]:
    target = tmp_path / "out.csv"
    result = _run("exportar", "-o", str(target))
    assert result.exit_code == 0, result.output
    with target.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def test_eggs_bigger_pack_is_cheaper_per_unit():
    _import("synthetic_eggs.html")
    small = _product_id("OVOS BRANCOS C/20")
    big = _product_id("OVOS BRANCOS C/30")
    assert _run("produtos", "definir-conteudo", str(small), "20", "UN").exit_code == 0
    assert _run("produtos", "definir-conteudo", str(big), "30", "UN").exit_code == 0

    result = _run("consultar", "ovos")
    assert result.exit_code == 0, result.output
    assert "Por UN" in result.output
    assert "R$ 0,55" in _row_containing(result.output, "R$ 16,50")
    assert "R$ 0,60" in _row_containing(result.output, "R$ 12,00")


def test_real_data_has_no_flip_between_total_and_per_liter(tmp_path):
    conn = db.connect(tmp_path / "prices.db")
    importing.import_receipt(conn, FIXTURES / "qrcode.html", DFReceiptParser())
    by_name = {p.canonical_name: p.id for p in catalog.list_products(conn)}
    catalog.set_product_content(conn, by_name["REFRI PEPSI PET 2L"], 2, "L")
    catalog.set_product_content(conn, by_name["REFRI ANT GUARANA PET 1.5L"], 1.5, "L")

    records = {r.canonical_name: r for r in search_prices(conn, "refri")}
    pepsi, guarana = records["REFRI PEPSI PET 2L"], records["REFRI ANT GUARANA PET 1.5L"]
    assert guarana.price_per_content == pytest.approx(4.99 / 1.5)
    assert pepsi.price_per_content == pytest.approx(6.99 / 2)
    assert guarana.price_per_content < pepsi.price_per_content
    assert guarana.unit_price < pepsi.unit_price


def test_rename_store_shows_in_search():
    _import("qrcode.html")
    result = _run("mercados", "renomear", "27.289.076/0013-79", "FL 3 Costa Águas Claras")
    assert result.exit_code == 0, result.output
    output = _run("consultar", "picanha").output
    assert "FL 3 Costa Águas Claras" in output
    assert "FL 3 COSTA MULTICANAL S A" not in output


def test_merge_via_cli_unifies_history():
    _import("qrcode.html", "qrcode-3.html")
    source = _product_id("TOMATE ITALIANO kg")
    target = _product_id("TOMATE ITALIANO UNIAO kg")
    result = _run("produtos", "fundir", str(source), str(target), "--sim")
    assert result.exit_code == 0, result.output

    output = _run("consultar", "tomate").output
    assert "2026-09-12" in output and "2026-09-07" in output
    assert "TOMATE ITALIANO kg" not in output
    assert output.count("TOMATE ITALIANO UNIAO kg") == 2


def test_reimport_is_idempotent_end_to_end(tmp_path):
    assert "20 itens novos, 0 já existiam" in _import("qrcode.html").output
    assert "0 itens novos, 20 já existiam" in _import("qrcode.html").output
    assert len(_export_rows(tmp_path)) == 20


def test_import_all_five_real_receipts_and_export(tmp_path):
    _import("qrcode.html", "qrcode-2.html", "qrcode-3.html", "qrcode-4.html", "qrcode-5.html")
    rows = _export_rows(tmp_path)
    assert len(rows) == 86
    assert {row["unit"] for row in rows} == {"UN", "KG"}

    result = _run("consultar", "banana")
    assert "Preços por KG" in result.output
    assert "BANANA PRATA kg" in result.output
    assert "Preços por UN" not in result.output


def test_unknown_unit_receipt_fails_loudly_and_writes_nothing(tmp_path):
    broken = tmp_path / "broken.html"
    broken.write_text(
        (FIXTURES / "qrcode-2.html").read_text(encoding="utf-8").replace("</strong>KG<strong>", "</strong>LT<strong>"),
        encoding="utf-8",
    )
    result = _run("importar", str(broken))
    assert result.exit_code == 1
    assert "'LT'" in result.stderr
    assert len(_export_rows(tmp_path)) == 0


_ALL_FIXTURES = ("qrcode.html", "qrcode-2.html", "qrcode-3.html", "qrcode-4.html", "qrcode-5.html")


def test_v2_import_review_search_by_tag(monkeypatch):
    _ai_env(monkeypatch)
    enrich_payload = [
        {"id": 11, "readable_name": "Linguiça de frango resfriada Aurora", "tags": ["carnes"], "content": None},
        {"id": 12, "readable_name": "Picanha bovina fatiada promoção", "tags": ["carnes"], "content": None},
        {"id": 13, "readable_name": "Fraldinha bovina promoção", "tags": ["carnes"], "content": None},
        {"id": 16, "readable_name": "Contra filé kg", "tags": ["carnes"], "content": None},
        {"id": 55, "readable_name": "Bacon fatiado", "tags": ["carnes"], "content": None},
    ]
    fake = ScriptedLlmClient(by_kind={"enrich": _enrich(enrich_payload)})
    _stub_client(monkeypatch, fake)

    result = _run("importar", *(str(FIXTURES / name) for name in _ALL_FIXTURES), "--sim")
    assert result.exit_code == 0, result.output

    listar = _run("produtos", "listar").output
    assert "Linguiça de frango resfriada Aurora" in listar

    tag_result = _run("consultar", "--tag", "carnes")
    assert tag_result.exit_code == 0, tag_result.output
    for name in ("Linguiça", "Picanha", "Fraldinha", "Contra fil", "Bacon"):
        assert name in tag_result.output

    calls_before = len(fake.calls)
    linguica_result = _run("consultar", "linguica")
    assert linguica_result.exit_code == 0
    assert "Linguiça" in linguica_result.output
    assert len(fake.calls) == calls_before  # found deterministically: no match call needed


def test_v2_fallback_then_permanent_fix(monkeypatch):
    _import("qrcode.html")  # imported with no AI configured: nothing reviewed
    _ai_env(monkeypatch)
    picanha_id = _product_id("PICANHA BOV FAT kg PROMO")
    fake = ScriptedLlmClient(by_kind={"match": _match([picanha_id])})
    _stub_client(monkeypatch, fake)

    result = _run("consultar", "carnes")
    assert result.exit_code == 0, result.output
    assert "PICANHA" in result.output
    assert any(line.startswith("Dica:") and "Encontrado pela IA" in line for line in result.output.splitlines())

    _run("produtos", "tag", str(picanha_id), "carnes")
    fake.calls.clear()

    result2 = _run("consultar", "--tag", "carnes")
    assert result2.exit_code == 0
    assert "PICANHA" in result2.output
    assert fake.calls == []


def test_v2_stores_show_address_and_branch_hint():
    result = _import("qrcode-3.html", "qrcode-4.html")
    assert "Filiais da mesma rede" in result.output
    assert "GUARA II" in result.output
    assert "CANDANGOLANDIA" in result.output

    listar = _run("mercados", "listar").output
    assert "GUARA II" in listar and "CANDANGOLANDIA" in listar

    consulta = _run("consultar", "tomate").output
    assert "GUARA II" in consulta or "CANDANGOLANDIA" in consulta


def test_v2_reimport_is_idempotent_and_silent(monkeypatch):
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient(by_kind={"enrich": _enrich([{"id": 1, "readable_name": "X", "tags": ["carnes"], "content": None}])})
    _stub_client(monkeypatch, fake)
    _run("importar", *(str(FIXTURES / name) for name in _ALL_FIXTURES), "--sim")
    fake.calls.clear()

    result = _run("importar", *(str(FIXTURES / name) for name in _ALL_FIXTURES))

    assert result.exit_code == 0, result.output
    assert result.output.count("0 itens novos") == 5
    assert fake.calls == []
    assert "Aplicado:" not in result.output


def test_v2_untag_and_rename_undo_ai_writes(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient(
        by_kind={"enrich": _enrich([{"id": 11, "readable_name": "Linguiça de frango Aurora", "tags": ["carnes"], "content": None}])}
    )
    _stub_client(monkeypatch, fake)
    _run("produtos", "revisar", "--sim")
    listar = _run("produtos", "listar").output
    assert "Linguiça de frango Aurora" in listar and "carnes" in listar

    _run("produtos", "tag", "11", "carnes", "--remover")
    _run("produtos", "renomear", "11", "LING FGO RESF AURORA kg")

    listar2 = _run("produtos", "listar").output
    assert "LING FGO RESF AURORA kg" in listar2
    assert "carnes" not in listar2


def test_v2_ai_log_has_one_line_per_attempt(monkeypatch, tmp_path):
    _ai_env(monkeypatch)
    fake = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich([{"id": 1, "readable_name": "X", "tags": ["carnes"], "content": None}]),
            "match": _match([]),
        }
    )
    _stub_client(monkeypatch, fake)
    _run("importar", str(FIXTURES / "qrcode.html"), "--sim")
    _run("consultar", "carnes")

    log_path = tmp_path / "ai_calls.jsonl"
    assert log_path.exists()
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    kinds = {line["call_kind"] for line in lines}
    assert kinds <= {"enrich", "merge", "match"}
    assert "enrich" in kinds
    for line in lines:
        assert isinstance(line["parsed_ok"], bool)
