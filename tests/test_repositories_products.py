import sqlite3

import pytest

from julius.repositories import products

STORE_A = "27289076001379"
STORE_B = "11832478000285"


@pytest.fixture
def conn_with_stores(conn):
    for cnpj in (STORE_A, STORE_B):
        conn.execute("INSERT INTO stores VALUES (?, ?, ?)", (cnpj, f"Store {cnpj}", f"Store {cnpj}"))
    return conn


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_resolve_creates_product_and_sku_on_first_sight(conn_with_stores):
    conn = conn_with_stores
    product_id = products.resolve_product_id(conn, STORE_A, "622", "REFRI PEPSI PET 2L")
    assert products.get_product(conn, product_id).canonical_name == "REFRI PEPSI PET 2L"
    assert _count(conn, "products") == 1
    assert _count(conn, "product_skus") == 1


def test_resolve_reuses_product_for_known_sku_even_if_description_changed(conn_with_stores):
    conn = conn_with_stores
    first = products.resolve_product_id(conn, STORE_A, "622", "REFRI PEPSI PET 2L")
    second = products.resolve_product_id(conn, STORE_A, "622", "REFRI PEPSI 2L PROMO")
    assert first == second
    assert products.get_product(conn, first).canonical_name == "REFRI PEPSI PET 2L"
    assert _count(conn, "products") == 1


def test_same_code_in_different_stores_are_different_products(conn_with_stores):
    conn = conn_with_stores
    degreaser = products.resolve_product_id(conn, STORE_A, "4134", "DESENGORD UAU 500ML GATILHO")
    broccoli = products.resolve_product_id(conn, STORE_B, "4134", "BROCOLE NINJA")
    assert degreaser != broccoli
    assert _count(conn, "products") == 2


def test_get_product_includes_sorted_tags(conn_with_stores):
    conn = conn_with_stores
    product_id = products.resolve_product_id(conn, STORE_A, "1", "TOMATE")
    products.add_tag(conn, product_id, "hortifruti")
    products.add_tag(conn, product_id, "cozinha")
    assert products.get_product(conn, product_id).tags == ("cozinha", "hortifruti")


def test_get_product_missing_returns_none(conn):
    assert products.get_product(conn, 999) is None


def test_list_products_sorted_by_name(conn_with_stores):
    conn = conn_with_stores
    products.resolve_product_id(conn, STORE_A, "1", "TOMATE")
    products.resolve_product_id(conn, STORE_A, "2", "ALHO")
    products.resolve_product_id(conn, STORE_A, "3", "CEBOLA")
    assert [p.canonical_name for p in products.list_products(conn)] == ["ALHO", "CEBOLA", "TOMATE"]


def test_rename_product_and_missing_raises(conn_with_stores):
    conn = conn_with_stores
    product_id = products.resolve_product_id(conn, STORE_A, "1", "LING FGO RESF AURORA kg")
    products.rename_product(conn, product_id, "Linguiça de frango Aurora")
    assert products.get_product(conn, product_id).canonical_name == "Linguiça de frango Aurora"
    with pytest.raises(LookupError):
        products.rename_product(conn, 999, "x")


def test_set_content_and_missing_raises(conn_with_stores):
    conn = conn_with_stores
    product_id = products.resolve_product_id(conn, STORE_A, "1", "MANTEIGA 500G")
    products.set_content(conn, product_id, 0.5, "KG")
    product = products.get_product(conn, product_id)
    assert (product.content_quantity, product.content_unit) == (0.5, "KG")
    with pytest.raises(LookupError):
        products.set_content(conn, 999, 1.0, "L")


def test_add_tag_is_idempotent_and_reuses_tag_row(conn_with_stores):
    conn = conn_with_stores
    a = products.resolve_product_id(conn, STORE_A, "1", "DETERGENTE")
    b = products.resolve_product_id(conn, STORE_A, "2", "SABAO EM PO")
    products.add_tag(conn, a, "limpeza")
    products.add_tag(conn, a, "limpeza")
    products.add_tag(conn, b, "limpeza")
    assert _count(conn, "tags") == 1
    assert _count(conn, "product_tags") == 2
    assert products.all_tag_names(conn) == ["limpeza"]
    with pytest.raises(LookupError):
        products.add_tag(conn, 999, "limpeza")


def test_product_ids_with_tag_and_unknown_tag_returns_empty(conn_with_stores):
    conn = conn_with_stores
    a = products.resolve_product_id(conn, STORE_A, "1", "TOMATE")
    b = products.resolve_product_id(conn, STORE_A, "2", "CEBOLA")
    products.resolve_product_id(conn, STORE_A, "3", "DETERGENTE")
    products.add_tag(conn, a, "hortifruti")
    products.add_tag(conn, b, "hortifruti")
    assert products.product_ids_with_tag(conn, "hortifruti") == [a, b]
    assert products.product_ids_with_tag(conn, "inexistente") == []


def test_reassign_skus_moves_all_skus(conn_with_stores):
    conn = conn_with_stores
    source = products.resolve_product_id(conn, STORE_A, "22039", "TOMATE ITALIANO UNIAO kg")
    target = products.resolve_product_id(conn, STORE_B, "7147", "TOMATE ITALIANO kg")
    products.reassign_skus(conn, source, target)
    assert products.resolve_product_id(conn, STORE_A, "22039", "whatever") == target
    assert _count(conn, "products") == 2


def test_delete_product_removes_tags_and_fails_if_still_referenced(conn_with_stores):
    conn = conn_with_stores
    source = products.resolve_product_id(conn, STORE_A, "22039", "TOMATE ITALIANO UNIAO kg")
    target = products.resolve_product_id(conn, STORE_B, "7147", "TOMATE ITALIANO kg")
    products.add_tag(conn, source, "hortifruti")
    with pytest.raises(sqlite3.IntegrityError):
        products.delete_product(conn, source)
    products.reassign_skus(conn, source, target)
    products.delete_product(conn, source)
    assert products.get_product(conn, source) is None
    assert conn.execute("SELECT count(*) FROM product_tags WHERE product_id = ?", (source,)).fetchone()[0] == 0
    with pytest.raises(LookupError):
        products.delete_product(conn, 999)
