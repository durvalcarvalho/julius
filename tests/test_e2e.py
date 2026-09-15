"""End-to-end flows through the CLI, the way a user would run them."""

import csv
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from julius.cli import app
from julius.infra import db
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
