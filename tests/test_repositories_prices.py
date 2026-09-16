import sqlite3

import pytest

from julius.domain.models import Receipt, ReceiptItem
from julius.repositories import prices, products, stores

STORE_CNPJ = "27289076001379"
OTHER_CNPJ = "11832478000285"
KEY_A = "1" * 44
KEY_B = "2" * 44


def _item(index: int = 1, code: str = "622", description: str = "REFRI PEPSI PET 2L", **overrides) -> ReceiptItem:
    values = dict(
        index=index,
        product_code=code,
        description=description,
        quantity=1.0,
        unit="UN",
        unit_price=6.99,
        total_price=6.99,
    )
    values.update(overrides)
    return ReceiptItem(**values)


def _receipt(key: str = KEY_A, issued_at: str = "2026-09-12T13:09:16", cnpj: str = STORE_CNPJ, *items) -> Receipt:
    return Receipt(
        access_key=key,
        issued_at=issued_at,
        store_cnpj=cnpj,
        store_legal_name="FL 3 COSTA MULTICANAL S A",
        items=tuple(items) or (_item(),),
    )


def _insert(conn, receipt: Receipt) -> list[bool]:
    stores.ensure_store(conn, receipt.store_cnpj, receipt.store_legal_name)
    results = []
    for item in receipt.items:
        product_id = products.resolve_product_id(conn, receipt.store_cnpj, item.product_code, item.description)
        results.append(prices.insert_price(conn, receipt, item, product_id))
    return results


def test_insert_price_returns_true_then_false_for_same_receipt_line(conn):
    assert _insert(conn, _receipt()) == [True]
    assert _insert(conn, _receipt()) == [False]
    assert prices.count(conn) == 1


def test_repeated_code_in_same_receipt_are_separate_rows(conn):
    receipt = _receipt(KEY_A, "2026-09-12T13:09:16", STORE_CNPJ, _item(index=1), _item(index=2))
    assert _insert(conn, receipt) == [True, True]
    assert prices.count(conn) == 2


def test_insert_price_with_unknown_store_raises_integrity_error(conn):
    stores.ensure_store(conn, STORE_CNPJ, "X")
    product_id = products.resolve_product_id(conn, STORE_CNPJ, "622", "REFRI")
    ghost = _receipt(KEY_A, "2026-09-12T13:09:16", "00000000000000")
    with pytest.raises(sqlite3.IntegrityError):
        prices.insert_price(conn, ghost, ghost.items[0], product_id)


def test_prices_for_products_joins_nickname_and_name(conn):
    _insert(conn, _receipt())
    stores.rename_store(conn, STORE_CNPJ, "FL3 Aguas Claras")
    (product_id, _), = products.product_names(conn)

    (record,) = prices.prices_for_products(conn, [product_id])

    assert record.store_nickname == "FL3 Aguas Claras"
    assert record.canonical_name == "REFRI PEPSI PET 2L"
    assert record.unit == "UN"
    assert record.unit_price == 6.99
    assert record.purchased_at == "2026-09-12T13:09:16"
    assert record.highlight is None


def test_prices_for_products_orders_newest_first(conn):
    _insert(conn, _receipt(KEY_A, "2026-09-01T10:00:00"))
    _insert(conn, _receipt(KEY_B, "2026-09-12T13:09:16"))
    (product_id, _), = products.product_names(conn)

    records = prices.prices_for_products(conn, [product_id])

    assert [r.purchased_at for r in records] == ["2026-09-12T13:09:16", "2026-09-01T10:00:00"]


def test_price_per_content_is_none_without_content_and_computed_with_it(conn):
    _insert(conn, _receipt())
    (product_id, _), = products.product_names(conn)
    assert prices.prices_for_products(conn, [product_id])[0].price_per_content is None

    products.set_content(conn, product_id, 2.0, "L")

    assert prices.prices_for_products(conn, [product_id])[0].price_per_content == pytest.approx(3.495)


def test_prices_for_products_empty_ids_returns_empty(conn):
    _insert(conn, _receipt())
    assert prices.prices_for_products(conn, []) == []


def test_prices_for_products_carry_store_address(conn):
    stores.ensure_store(conn, STORE_CNPJ, "FL 3 COSTA MULTICANAL S A", "QUADRA QE 30, GUARA II, BRASILIA, DF")
    _insert(conn, _receipt())
    (product_id, _), = products.product_names(conn)

    (record,) = prices.prices_for_products(conn, [product_id])

    assert record.store_address == "QUADRA QE 30, GUARA II, BRASILIA, DF"


def test_prices_for_products_address_is_none_for_store_without_one(conn):
    _insert(conn, _receipt())
    (product_id, _), = products.product_names(conn)
    assert prices.prices_for_products(conn, [product_id])[0].store_address is None


def test_prices_for_products_carries_kind(conn):
    _insert(conn, _receipt())
    (product_id, _), = products.product_names(conn)
    assert prices.prices_for_products(conn, [product_id])[0].kind is None

    products.set_kind(conn, product_id, "refrigerante")

    assert prices.prices_for_products(conn, [product_id])[0].kind == "refrigerante"


def test_export_rows_has_exact_columns_in_order_and_is_sorted(conn):
    _insert(conn, _receipt(KEY_B, "2026-09-12T13:09:16", STORE_CNPJ, _item(index=2), _item(index=1)))
    _insert(conn, _receipt(KEY_A, "2026-09-01T10:00:00"))

    rows = prices.export_rows(conn)

    assert [list(row) for row in rows] == [list(prices.EXPORT_COLUMNS)] * 3
    assert [(r["purchased_at"], r["access_key"], r["item_index"]) for r in rows] == [
        ("2026-09-01T10:00:00", KEY_A, 1),
        ("2026-09-12T13:09:16", KEY_B, 1),
        ("2026-09-12T13:09:16", KEY_B, 2),
    ]
    assert rows[0]["store_nickname"] == "FL 3 COSTA MULTICANAL S A"
    assert rows[0]["canonical_name"] == "REFRI PEPSI PET 2L"


def test_reassign_product_moves_rows_and_leaves_others(conn):
    _insert(conn, _receipt(KEY_A, "2026-09-12T13:09:16", STORE_CNPJ, _item(code="7147", description="TOMATE ITALIANO kg")))
    _insert(conn, _receipt(KEY_B, "2026-09-07T18:18:30", OTHER_CNPJ, _item(code="22039", description="TOMATE ITALIANO UNIAO kg")))
    _insert(conn, _receipt("3" * 44, "2026-09-05T16:50:34", STORE_CNPJ, _item(code="3921", description="CONTRA FILE KG")))
    ids = {name: pid for pid, name in products.product_names(conn)}
    source, target, other = ids["TOMATE ITALIANO kg"], ids["TOMATE ITALIANO UNIAO kg"], ids["CONTRA FILE KG"]

    prices.reassign_product(conn, source, target)

    assert prices.prices_for_products(conn, [source]) == []
    assert len(prices.prices_for_products(conn, [target])) == 2
    assert len(prices.prices_for_products(conn, [other])) == 1


def test_count(conn):
    assert prices.count(conn) == 0
    _insert(conn, _receipt(KEY_A, "2026-09-12T13:09:16", STORE_CNPJ, _item(index=1), _item(index=2), _item(index=3)))
    assert prices.count(conn) == 3
