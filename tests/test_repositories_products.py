import sqlite3

import pytest

from julius.repositories import products

STORE_A = "27289076001379"
STORE_B = "11832478000285"
SEEDED_TAGS = sorted(
    [
        "hortifruti", "carnes", "frios", "laticinios", "padaria", "mercearia",
        "bebidas", "limpeza", "higiene", "congelados", "temperos", "doces", "utilidades",
    ]
)  # migration 0002


@pytest.fixture
def conn_with_stores(conn):
    for cnpj in (STORE_A, STORE_B):
        conn.execute(
            "INSERT INTO stores (cnpj, legal_name, nickname) VALUES (?, ?, ?)", (cnpj, f"Store {cnpj}", f"Store {cnpj}")
        )
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
    assert _count(conn, "tags") == 13  # "limpeza" is one of the 13 seeded by migration 0002
    assert _count(conn, "product_tags") == 2
    assert products.all_tag_names(conn) == SEEDED_TAGS
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


def test_remove_tag_deletes_link_but_keeps_tag_row(conn_with_stores):
    conn = conn_with_stores
    a = products.resolve_product_id(conn, STORE_A, "1", "DETERGENTE")
    b = products.resolve_product_id(conn, STORE_A, "2", "SABAO EM PO")
    products.add_tag(conn, a, "limpeza")
    products.add_tag(conn, b, "limpeza")

    products.remove_tag(conn, a, "limpeza")

    assert products.get_product(conn, a).tags == ()
    assert products.get_product(conn, b).tags == ("limpeza",)
    assert _count(conn, "tags") == 13  # seeded row stays: still used by b, and it's a category, not user data


@pytest.mark.parametrize(
    ("product_id", "tag_name"),
    [(9999, "limpeza"), ("known", "nunca-usada")],
)
def test_remove_tag_unknown_product_or_missing_link_raises_lookup_error(conn_with_stores, product_id, tag_name):
    conn = conn_with_stores
    known = products.resolve_product_id(conn, STORE_A, "1", "DETERGENTE")
    if product_id == "known":
        product_id = known
    with pytest.raises(LookupError):
        products.remove_tag(conn, product_id, tag_name)


def test_untagged_product_ids_lists_only_products_without_tags_in_id_order(conn_with_stores):
    conn = conn_with_stores
    a = products.resolve_product_id(conn, STORE_A, "1", "DETERGENTE")
    b = products.resolve_product_id(conn, STORE_A, "2", "SABAO EM PO")
    c = products.resolve_product_id(conn, STORE_A, "3", "TOMATE")
    products.add_tag(conn, b, "limpeza")
    assert products.untagged_product_ids(conn) == sorted([a, c])


def test_has_raw_name_true_after_import_false_after_rename(conn_with_stores):
    conn = conn_with_stores
    product_id = products.resolve_product_id(conn, STORE_A, "1", "LING FGO RESF AURORA kg")
    conn.execute(
        "INSERT INTO prices (access_key, item_index, purchased_at, store_cnpj, product_id, product_code, "
        "description, quantity, unit, unit_price, total_price) VALUES (?, 1, ?, ?, ?, ?, ?, 1, 'KG', 1, 1)",
        ("k" * 44, "2026-09-12T13:09:16", STORE_A, product_id, "1", "LING FGO RESF AURORA kg"),
    )
    assert products.has_raw_name(conn, product_id) is True

    products.rename_product(conn, product_id, "Linguiça de frango resfriada Aurora")
    assert products.has_raw_name(conn, product_id) is False


def test_has_raw_name_false_for_product_without_prices(conn):
    product_id = conn.execute("INSERT INTO products (canonical_name) VALUES ('X')").lastrowid
    assert products.has_raw_name(conn, product_id) is False


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


def test_set_kind_and_read_back(conn_with_stores):
    conn = conn_with_stores
    pid = products.resolve_product_id(conn, STORE_A, "1", "TOMATE ITALIANO kg")
    products.set_kind(conn, pid, "Tomate")
    assert products.get_product(conn, pid).kind == "tomate"


def test_set_kind_reuses_existing_spelling(conn_with_stores):
    conn = conn_with_stores
    first = products.resolve_product_id(conn, STORE_A, "1", "ACAI POLPA")
    second = products.resolve_product_id(conn, STORE_B, "2", "ACAI ZERO")
    products.set_kind(conn, first, "açaí")
    products.set_kind(conn, second, "ACAI")
    assert products.get_product(conn, second).kind == "açaí"


def test_set_kind_none_clears(conn_with_stores):
    conn = conn_with_stores
    pid = products.resolve_product_id(conn, STORE_A, "1", "TOMATE")
    products.set_kind(conn, pid, "tomate")
    products.set_kind(conn, pid, None)
    assert products.get_product(conn, pid).kind is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_set_kind_blank_raises(conn_with_stores, blank):
    conn = conn_with_stores
    pid = products.resolve_product_id(conn, STORE_A, "1", "TOMATE")
    with pytest.raises(ValueError):
        products.set_kind(conn, pid, blank)
    assert products.get_product(conn, pid).kind is None


def test_set_kind_unknown_product_raises(conn):
    with pytest.raises(LookupError):
        products.set_kind(conn, 999, "tomate")


def test_all_kinds_distinct_and_sorted(conn_with_stores):
    conn = conn_with_stores
    assert products.all_kinds(conn) == []
    ids = [products.resolve_product_id(conn, STORE_A, str(i), f"P{i}") for i in range(3)]
    products.set_kind(conn, ids[0], "tomate")
    products.set_kind(conn, ids[1], "cebola")
    products.set_kind(conn, ids[2], "tomate")
    assert products.all_kinds(conn) == ["cebola", "tomate"]


def test_clear_content_clears_both_columns(conn_with_stores):
    conn = conn_with_stores
    pid = products.resolve_product_id(conn, STORE_A, "1", "AGUA 500ML")
    products.set_content(conn, pid, 0.5, "L")
    products.clear_content(conn, pid)
    product = products.get_product(conn, pid)
    assert (product.content_quantity, product.content_unit) == (None, None)


def test_clear_content_unknown_product_raises(conn):
    with pytest.raises(LookupError):
        products.clear_content(conn, 999)
