from pathlib import Path

import pytest

from julius.domain.models import ImportResult
from julius.domain.normalization import UnknownUnitError
from julius.parsers import ReceiptParseError
from julius.parsers.df import DFReceiptParser
from julius.repositories import stores
from julius.services.importing import import_receipt

FIXTURES = Path(__file__).parent / "fixtures"
PARSER = DFReceiptParser()


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _import(conn, name: str) -> ImportResult:
    return import_receipt(conn, FIXTURES / name, PARSER)


def test_import_single_receipt(conn):
    result = _import(conn, "qrcode.html")
    assert (result.new_items, result.existing_items) == (20, 0)
    assert _count(conn, "stores") == 1
    assert _count(conn, "products") == 15
    assert _count(conn, "prices") == 20


def test_reimport_is_idempotent(conn):
    _import(conn, "qrcode.html")
    assert _import(conn, "qrcode.html") == ImportResult(new_items=0, existing_items=20)
    assert (_count(conn, "stores"), _count(conn, "products"), _count(conn, "prices")) == (1, 15, 20)


def test_import_three_receipts_accumulates(conn):
    for name in ["qrcode.html", "qrcode-2.html", "qrcode-3.html"]:
        _import(conn, name)
    assert (_count(conn, "stores"), _count(conn, "products"), _count(conn, "prices")) == (3, 21, 27)


def test_import_all_five_fixtures(conn):
    for name in ["qrcode.html", "qrcode-2.html", "qrcode-3.html", "qrcode-4.html", "qrcode-5.html"]:
        _import(conn, name)
    assert _count(conn, "prices") == 86
    units = {row[0] for row in conn.execute("SELECT DISTINCT unit FROM prices")}
    assert units <= {"UN", "KG"}


def test_nickname_survives_reimport(conn):
    _import(conn, "qrcode.html")
    stores.rename_store(conn, "27289076001379", "FL 3 Costa")
    conn.commit()
    _import(conn, "qrcode.html")
    assert stores.get_store(conn, "27289076001379").nickname == "FL 3 Costa"


def test_new_product_ids_lists_only_products_created_in_this_call(conn):
    first = _import(conn, "qrcode.html")
    assert len(first.new_product_ids) == 15
    assert len(set(first.new_product_ids)) == 15
    assert set(first.new_product_ids) == {row[0] for row in conn.execute("SELECT id FROM products")}
    assert _import(conn, "qrcode.html").new_product_ids == ()
    assert len(_import(conn, "qrcode-3.html").new_product_ids) == 5


def test_same_sku_reuses_product_across_imports(conn):
    _import(conn, "qrcode.html")
    _import(conn, "qrcode.html")
    assert _count(conn, "products") == 15
    assert _count(conn, "product_skus") == 15


def test_parse_error_writes_nothing(conn, tmp_path):
    bad = tmp_path / "bad.html"
    bad.write_text("<html><body>nada aqui</body></html>", encoding="utf-8")
    with pytest.raises(ReceiptParseError):
        import_receipt(conn, bad, PARSER)
    assert _count(conn, "prices") == 0
    assert _count(conn, "stores") == 0


def test_unknown_unit_writes_nothing(conn, tmp_path):
    broken = tmp_path / "qrcode-2.html"
    broken.write_text((FIXTURES / "qrcode-2.html").read_text(encoding="utf-8").replace("KG", "LT"), encoding="utf-8")
    with pytest.raises(UnknownUnitError, match="'LT'"):
        import_receipt(conn, broken, PARSER)
    assert _count(conn, "prices") == 0
    assert _count(conn, "stores") == 0
    assert _count(conn, "products") == 0


def test_missing_file_raises_file_not_found(conn, tmp_path):
    with pytest.raises(FileNotFoundError):
        import_receipt(conn, tmp_path / "nao-existe.html", PARSER)
