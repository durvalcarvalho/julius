import csv
import sqlite3
from pathlib import Path

from julius.parsers.df import DFReceiptParser
from julius.repositories import prices, products, stores
from julius.repositories.prices import EXPORT_COLUMNS
from julius.services.export import export_csv

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _import_fixture(conn: sqlite3.Connection, name: str) -> None:
    receipt = DFReceiptParser().parse((FIXTURES_DIR / name).read_text(encoding="utf-8"), source=name)
    with conn:
        stores.ensure_store(conn, receipt.store_cnpj, receipt.store_legal_name, receipt.store_address)
        for item in receipt.items:
            product_id = products.resolve_product_id(conn, receipt.store_cnpj, item.product_code, item.description)
            prices.insert_price(conn, receipt, item, product_id)


def _read(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle, delimiter=";"))


def test_export_empty_db_writes_header_only_and_returns_zero(conn, tmp_path):
    destination = tmp_path / "out.csv"
    assert export_csv(conn, destination) == 0
    assert _read(destination) == [list(EXPORT_COLUMNS)]


def test_export_after_import_writes_all_rows(conn, tmp_path):
    _import_fixture(conn, "qrcode.html")
    destination = tmp_path / "out.csv"
    assert export_csv(conn, destination) == 20
    assert len(_read(destination)) == 21


def test_export_columns_in_exact_order(conn, tmp_path):
    _import_fixture(conn, "qrcode-2.html")
    destination = tmp_path / "out.csv"
    export_csv(conn, destination)
    header, row = _read(destination)
    assert header == list(EXPORT_COLUMNS)
    assert row[header.index("quantity")] == "1.532"
    assert row[header.index("unit_price")] == "53.99"
    assert row[header.index("unit")] == "KG"


def test_export_creates_parent_directories(conn, tmp_path):
    destination = tmp_path / "deep" / "er" / "out.csv"
    export_csv(conn, destination)
    assert destination.exists()


def test_export_overwrites_existing_file(conn, tmp_path):
    destination = tmp_path / "out.csv"
    destination.write_text("stale content\nmore stale\n", encoding="utf-8")
    export_csv(conn, destination)
    assert _read(destination) == [list(EXPORT_COLUMNS)]


def test_export_rows_contain_store_nickname_not_only_cnpj(conn, tmp_path):
    _import_fixture(conn, "qrcode-2.html")
    stores.rename_store(conn, "20209736000181", "HTP Guará")
    destination = tmp_path / "out.csv"
    export_csv(conn, destination)
    header, row = _read(destination)
    assert row[header.index("store_nickname")] == "HTP Guará"
    assert row[header.index("store_cnpj")] == "20209736000181"


def test_export_header_includes_store_address_after_nickname(conn, tmp_path):
    destination = tmp_path / "out.csv"
    export_csv(conn, destination)
    header = _read(destination)[0]
    assert header.index("store_address") == header.index("store_nickname") + 1


def test_export_writes_address_value_and_empty_when_null(conn, tmp_path):
    _import_fixture(conn, "qrcode-3.html")
    destination = tmp_path / "out.csv"
    export_csv(conn, destination)
    header, *rows = _read(destination)
    assert rows[0][header.index("store_address")].endswith("GUARA II, BRASILIA, DF")

    conn.execute("UPDATE stores SET address = NULL")
    destination2 = tmp_path / "out2.csv"
    export_csv(conn, destination2)
    header2, *rows2 = _read(destination2)
    assert rows2[0][header2.index("store_address")] == ""
