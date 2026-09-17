"""End-to-end flows through the CLI, the way a user would run them."""

import csv
import json
import re
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import julius.cli.products as products_cli
import julius.cli.receipts as receipts_cli
from conftest import copied_fixtures, restore_fixture
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
    monkeypatch.setattr(sys.modules[__name__], "FIXTURES", copied_fixtures(tmp_path))
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
    result = _run("importar", *(str(restore_fixture(FIXTURES, name)) for name in names))
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
    result = _run("produtos", "fundir", str(source), str(target))
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

    result = _run("importar", *(str(restore_fixture(FIXTURES, name)) for name in _ALL_FIXTURES), "--sim")
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
    _run("importar", *(str(restore_fixture(FIXTURES, name)) for name in _ALL_FIXTURES), "--sim")
    fake.calls.clear()

    result = _run("importar", *(str(restore_fixture(FIXTURES, name)) for name in _ALL_FIXTURES))

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
    _run("importar", str(restore_fixture(FIXTURES, "qrcode.html")), "--sim")
    _run("consultar", "carnes")

    log_path = tmp_path / "ai_calls.jsonl"
    assert log_path.exists()
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    kinds = {line["call_kind"] for line in lines}
    assert kinds <= {"enrich", "merge", "match"}
    assert "enrich" in kinds
    for line in lines:
        assert isinstance(line["parsed_ok"], bool)


def test_e2e_comparar_after_import_and_kinds():
    _import("qrcode.html", "qrcode-3.html")
    output = _run("produtos", "listar").output
    ids = [int(match.group(1)) for match in re.finditer(r"│\s*(\d+)\s*│\s*TOMATE ITALIANO", output)]
    assert len(ids) == 2
    for product_id in ids:
        assert _run("produtos", "tipo", str(product_id), "tomate").exit_code == 0

    result = _run("mercados", "comparar")

    assert result.exit_code == 0, result.output
    assert "tomate · por KG" in result.output
    price_rows = [line for line in result.output.splitlines() if "R$" in line]
    assert "FL 3 COSTA" in price_rows[0] and "R$ 11,89" in price_rows[0]
    assert "DONA DE CASA" in price_rows[1] and "R$ 14,99" in price_rows[1]
    assert "base: 1 grupo · 07/09 a 12/09" in result.output


def test_e2e_import_twice_reports_lower_price(monkeypatch):
    _import("qrcode-3.html")
    dona_tomato = _product_id("TOMATE ITALIANO kg")
    assert _run("produtos", "tipo", str(dona_tomato), "tomate").exit_code == 0
    _ai_env(monkeypatch)
    _stub_client(
        monkeypatch,
        ScriptedLlmClient(
            by_kind={
                "enrich": LlmResponse(
                    json.dumps(
                        {
                            "products": [
                                {
                                    "id": 19,
                                    "readable_name": "Tomate Italiano União",
                                    "tags": ["hortifruti"],
                                    "kind": "tomate",
                                }
                            ]
                        }
                    ),
                    10,
                    5,
                ),
                "merge": LlmResponse(json.dumps({"pairs": []}), 10, 5),
            }
        ),
    )

    result = _import("qrcode.html")

    assert result.exit_code == 0, result.output
    signal = next(line for line in result.output.splitlines() if "↓" in line)
    assert "Tomate Italiano União" in signal and "R$ 11,89" in signal
    assert "menor preço já pago" in signal


def test_e2e_import_from_inbox_end_to_end(tmp_path):
    inbox = tmp_path / "entrada"
    inbox.mkdir()
    shutil.copy2(FIXTURES / "qrcode-3.html", inbox / "qrcode.html")

    result = _run("importar")

    assert result.exit_code == 0, result.output
    assert "6 itens novos" in result.output
    assert list(inbox.glob("*.html")) == []
    (archived,) = list((inbox / "importados").iterdir())
    assert archived.name.startswith("2026-09-07_")
    assert "TOMATE" in _run("produtos", "listar").output


def test_e2e_import_from_inbox_is_idempotent(tmp_path):
    inbox = tmp_path / "entrada"
    inbox.mkdir()
    shutil.copy2(FIXTURES / "qrcode-3.html", inbox / "qrcode.html")
    assert _run("importar").exit_code == 0

    again = _run("importar")

    assert again.exit_code == 0, again.output
    assert "Nada para importar" in again.output
    conn = db.connect(tmp_path / "prices.db")
    assert conn.execute("SELECT count(*) FROM prices").fetchone()[0] == 6


def test_v22_full_cycle(tmp_path, monkeypatch):
    inbox = tmp_path / "entrada"
    inbox.mkdir()
    for name in ("qrcode-3.html", "qrcode.html"):
        shutil.copy2(FIXTURES / name, inbox / name)
    _ai_env(monkeypatch)
    _stub_client(
        monkeypatch,
        ScriptedLlmClient(
            by_kind={
                "enrich": LlmResponse(
                    json.dumps(
                        {
                            "products": [
                                {"id": 4, "readable_name": "Tomate Italiano", "tags": ["hortifruti"], "kind": "tomate"},
                                {
                                    "id": 19,
                                    "readable_name": "Tomate Italiano União",
                                    "tags": ["hortifruti"],
                                    "kind": "tomate",
                                },
                                {
                                    "id": 6,
                                    "readable_name": "Refrigerante Pepsi 2L",
                                    "tags": ["bebidas"],
                                    "content": {"quantity": 2, "unit": "L"},
                                    "kind": "refrigerante",
                                },
                            ]
                        }
                    ),
                    10,
                    5,
                ),
                "merge": LlmResponse(json.dumps({"pairs": []}), 10, 5),
            }
        ),
    )

    imported = _run("importar")

    assert imported.exit_code == 0, imported.output
    conn = db.connect(tmp_path / "prices.db")
    assert conn.execute("SELECT count(*) FROM prices").fetchone()[0] == 26
    kinds = dict(conn.execute("SELECT id, kind FROM products WHERE kind IS NOT NULL"))
    assert kinds == {4: "tomate", 19: "tomate", 6: "refrigerante"}
    assert conn.execute("SELECT content_quantity, content_unit FROM products WHERE id = 6").fetchone()[:] == (2.0, "L")
    conn.close()

    actions = [json.loads(line) for line in (tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {action["field"] for action in actions} == {"name", "tag", "content", "kind"}
    assert list(inbox.glob("*.html")) == []
    archived = sorted(path.name for path in (inbox / "importados").iterdir())
    assert archived[0].startswith("2026-09-07_") and archived[1].startswith("2026-09-12_")

    audit = _run("produtos", "revisar", "--ultimas-acoes")
    assert audit.exit_code == 0, audit.output
    assert "julius produtos tipo 19 --remover" in audit.output

    consulta = _run("consultar", "tomate")
    assert consulta.exit_code == 0, consulta.output
    assert "Dia" in consulta.output and "seg" in consulta.output

    comparar = _run("mercados", "comparar")
    assert comparar.exit_code == 0, comparar.output
    assert "tomate · por KG" in comparar.output
    assert "FL 3 COSTA" in comparar.output and "DONA DE CASA" in comparar.output
    assert "base: 1 grupo · 07/09 a 12/09" in comparar.output

    assert _run("produtos", "tipo", "19", "--remover").exit_code == 0
    after_undo = _run("mercados", "comparar")
    assert after_undo.exit_code == 0, after_undo.output
    assert "tomate · por KG" not in after_undo.output


def _packaging(items: list[dict]) -> LlmResponse:
    return LlmResponse(json.dumps({"packaging": items}), 100, 50)


def test_v23_review_cycle(monkeypatch, tmp_path):
    """One pass of the v2.3 review: label content is written on sight, a KG product is never asked
    about, and the one UN product the AI refused becomes the single question on screen."""
    _import("qrcode.html")
    _ai_env(monkeypatch)
    from julius.cli import _review

    monkeypatch.setattr(_review, "_is_interactive", lambda: True)
    assert _run("produtos", "renomear", "12", "Picanha bovina").exit_code == 0

    enrich = _enrich(
        [
            # content read straight off the label: written without asking
            {"id": 5, "readable_name": "Sal Parrilla Lebre 500g", "tags": ["temperos"],
             "content": {"quantity": 0.5, "unit": "KG"}, "kind": "sal"},
            # sold by UN, the AI refuses the content: this is the only question
            {"id": 6, "readable_name": "Prato Redondo Descartável 21cm", "tags": ["utilidades"],
             "content": None, "kind": "prato descartável"},
            # sold by KG: content is not owed, so it is never asked about
            {"id": 12, "readable_name": "Picanha bovina", "tags": ["carnes"], "content": None, "kind": "picanha"},
        ]
    )
    client = ScriptedLlmClient(
        by_kind={
            "enrich": enrich,
            "packaging": _packaging(
                [{"id": 6, "form": "pack", "candidates": [{"quantity": 10, "unit": "UN"}, {"quantity": 20, "unit": "UN"}]}]
            ),
            "merge": LlmResponse(json.dumps({"pairs": []}), 10, 5),
        }
    )
    _stub_client(monkeypatch, client)

    first = _run("produtos", "revisar", input="1\n")

    assert first.exit_code == 0, first.output
    assert "— categoria" not in first.output  # the category question is gone for good
    assert "[1] 10 UN · pacote" in first.output and "[2] 20 UN · pacote" in first.output
    assert "Picanha bovina — conteúdo" not in first.output  # KG product, nothing to ask
    # the coupon text and the readable name are different columns
    renamed_row = _row_containing(first.output, "PICANHA BOV FAT kg PROMO")
    assert "Picanha bovina" in renamed_row

    listar = _run("produtos", "listar").output
    assert "0,5 KG" in _row_containing(listar, "Sal Parrilla Lebre 500g")  # label content, no question
    assert "10 UN" in _row_containing(listar, "Prato Redondo Descartável 21cm")  # the answered question

    actions = [json.loads(line) for line in (tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    answered = [action for action in actions if action["field"] == "content" and action["product_id"] == 6]
    assert answered[-1]["undo"] == "julius produtos definir-conteudo 6 --remover"

    second = _run("produtos", "revisar", input="\n")

    assert second.exit_code == 0, second.output
    assert "Prato Redondo Descartável 21cm — conteúdo" not in second.output  # resolved, gone from the queue


def test_v23_kg_product_never_asked_for_content(monkeypatch):
    _import("qrcode.html")
    _ai_env(monkeypatch)
    from julius.cli import _review

    monkeypatch.setattr(_review, "_is_interactive", lambda: True)
    client = ScriptedLlmClient(
        by_kind={
            "enrich": _enrich([{"id": 11, "readable_name": "Linguiça Aurora", "tags": ["carnes"], "content": None}]),
            "packaging": _packaging([{"id": 11, "form": "weight", "candidates": [{"quantity": 1, "unit": "KG"}]}]),
            "merge": LlmResponse(json.dumps({"pairs": []}), 10, 5),
        }
    )
    _stub_client(monkeypatch, client)

    result = _run("produtos", "revisar")  # no input at all: nothing may block

    assert result.exit_code == 0, result.output
    assert "— conteúdo" not in result.output
    assert [call for call in client.calls if '"packaging"' in call[0]] == []
