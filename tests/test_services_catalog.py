from pathlib import Path

import pytest

from julius.parsers.df import DFReceiptParser
from julius.repositories import prices, products, stores
from julius.services import catalog

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CNPJ = "00000000000191"


def _import(conn, fixture_name):
    receipt = DFReceiptParser().parse((FIXTURES_DIR / fixture_name).read_text(encoding="utf-8"), fixture_name)
    with conn:
        stores.ensure_store(conn, receipt.store_cnpj, receipt.store_legal_name)
        for item in receipt.items:
            product_id = products.resolve_product_id(conn, receipt.store_cnpj, item.product_code, item.description)
            prices.insert_price(conn, receipt, item, product_id)
    return receipt


def _product(conn, name, code):
    with conn:
        stores.ensure_store(conn, CNPJ, "Legal Name")
        return products.resolve_product_id(conn, CNPJ, code, name)


def _tomato_ids(conn):
    return sorted(pid for pid, name in products.product_names(conn) if name.startswith("TOMATE ITALIANO"))


def test_rename_store_strips_and_saves(conn):
    stores.ensure_store(conn, CNPJ, "Legal Name")
    catalog.rename_store(conn, CNPJ, "  Loja X  ")
    assert stores.get_store(conn, CNPJ).nickname == "Loja X"


def test_rename_store_blank_raises_value_error(conn):
    stores.ensure_store(conn, CNPJ, "Legal Name")
    with pytest.raises(ValueError, match="blank"):
        catalog.rename_store(conn, CNPJ, "   ")


def test_rename_store_unknown_raises_lookup_error(conn):
    with pytest.raises(LookupError):
        catalog.rename_store(conn, "99999999999999", "X")


def test_rename_product_and_errors(conn):
    product_id = _product(conn, "OLD", "1")
    catalog.rename_product(conn, product_id, "  New Name ")
    assert products.get_product(conn, product_id).canonical_name == "New Name"
    with pytest.raises(ValueError, match="blank"):
        catalog.rename_product(conn, product_id, " ")
    with pytest.raises(LookupError):
        catalog.rename_product(conn, 9999, "X")


def test_merge_moves_skus_prices_and_tags_then_deletes_source(conn):
    _import(conn, "qrcode.html")
    _import(conn, "qrcode-3.html")
    source_id, target_id = _tomato_ids(conn)
    catalog.tag_product(conn, source_id, "hortifruti")
    products_before = len(products.list_products(conn))
    prices_before = prices.count(conn)

    catalog.merge_products(conn, source_id, target_id)

    merged = prices.prices_for_products(conn, [target_id])
    assert {record.purchased_at[:10] for record in merged} == {"2026-09-12", "2026-09-07"}
    assert products.get_product(conn, source_id) is None
    assert products.get_product(conn, target_id).tags == ("hortifruti",)
    assert len(products.list_products(conn)) == products_before - 1
    assert prices.count(conn) == prices_before
    assert _tomato_ids(conn) == [target_id]


def test_merge_same_id_raises_value_error(conn):
    product_id = _product(conn, "A", "1")
    with pytest.raises(ValueError):
        catalog.merge_products(conn, product_id, product_id)


def test_merge_unknown_id_raises_lookup_error_and_changes_nothing(conn):
    receipt = _import(conn, "qrcode-2.html")
    (source_id,) = [pid for pid, _ in products.product_names(conn)]
    with pytest.raises(LookupError):
        catalog.merge_products(conn, source_id, 9999)
    item = receipt.items[0]
    assert products.resolve_product_id(conn, receipt.store_cnpj, item.product_code, item.description) == source_id
    assert len(prices.prices_for_products(conn, [source_id])) == 1
    assert products.get_product(conn, source_id) is not None


def test_merge_copies_content_when_target_has_none(conn):
    source_id = _product(conn, "A", "1")
    target_id = _product(conn, "B", "2")
    catalog.set_product_content(conn, source_id, 500, "G")
    catalog.merge_products(conn, source_id, target_id)
    target = products.get_product(conn, target_id)
    assert (target.content_quantity, target.content_unit) == (0.5, "KG")


def test_merge_keeps_target_content_when_present(conn):
    source_id = _product(conn, "A", "1")
    target_id = _product(conn, "B", "2")
    catalog.set_product_content(conn, source_id, 500, "G")
    catalog.set_product_content(conn, target_id, 2, "L")
    catalog.merge_products(conn, source_id, target_id)
    target = products.get_product(conn, target_id)
    assert (target.content_quantity, target.content_unit) == (2.0, "L")


def test_tag_product_normalizes_case_and_whitespace(conn):
    product_id = _product(conn, "A", "1")
    catalog.tag_product(conn, product_id, " Limpeza ")
    catalog.tag_product(conn, product_id, "limpeza")
    assert products.get_product(conn, product_id).tags == ("limpeza",)
    assert products.all_tag_names(conn) == ["limpeza"]


def test_tag_product_blank_raises(conn):
    product_id = _product(conn, "A", "1")
    with pytest.raises(ValueError, match="blank"):
        catalog.tag_product(conn, product_id, "  ")
    assert products.all_tag_names(conn) == []


def test_set_product_content_normalizes_grams_to_kilograms(conn):
    product_id = _product(conn, "A", "1")
    catalog.set_product_content(conn, product_id, 500, "G")
    product = products.get_product(conn, product_id)
    assert (product.content_quantity, product.content_unit) == (0.5, "KG")


def test_set_product_content_rejects_bad_unit_and_non_positive(conn):
    product_id = _product(conn, "A", "1")
    with pytest.raises(ValueError):
        catalog.set_product_content(conn, product_id, 1, "OZ")
    with pytest.raises(ValueError):
        catalog.set_product_content(conn, product_id, 0, "KG")
    assert products.get_product(conn, product_id).content_quantity is None
