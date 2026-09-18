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


def _add_price(conn, product_id: int, unit: str, purchased_at: str = "2026-09-12T13:09:16", description: str = "X"):
    index = _count(conn, "prices") + 1
    conn.execute(
        "INSERT INTO prices (access_key, item_index, purchased_at, store_cnpj, product_id, product_code, "
        "description, quantity, unit, unit_price, total_price) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 1, 1)",
        ("k" * 44, index, purchased_at, STORE_A, product_id, str(product_id), description, unit),
    )


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


def test_set_kind_reuses_existing_spelling_across_plural(conn_with_stores):
    """Measured on the real database: `ovo` (Assaí) and `ovos` (Costa) are the same 30-egg box in
    two stores, and the trailing letter alone kept them from ever comparing."""
    conn = conn_with_stores
    first = products.resolve_product_id(conn, STORE_A, "1", "OVO BCO GRANDE C/30")
    second = products.resolve_product_id(conn, STORE_B, "2", "OVOS IANA 30UN MEDIO BCO")
    products.set_kind(conn, first, "ovo")
    products.set_kind(conn, second, "ovos")
    assert products.get_product(conn, second).kind == "ovo"


def test_set_kind_keeps_a_plural_with_no_singular_in_the_catalogue(conn_with_stores):
    """The rule matches an existing spelling, it never rewrites — so `brócolis` stays whole."""
    conn = conn_with_stores
    pid = products.resolve_product_id(conn, STORE_A, "1", "BROCOLE NINJA")
    products.set_kind(conn, pid, "brócolis")
    assert products.get_product(conn, pid).kind == "brócolis"


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


def _complete_product(conn, code: str, name: str) -> int:
    product_id = products.resolve_product_id(conn, STORE_A, code, name)
    products.add_tag(conn, product_id, "mercearia")
    products.set_kind(conn, product_id, "generico")
    products.set_content(conn, product_id, 1, "UN")
    return product_id


def test_incomplete_includes_product_without_kind(conn_with_stores):
    conn = conn_with_stores
    product_id = _complete_product(conn, "1", "AGUA 500ML")
    products.set_kind(conn, product_id, None)
    assert products.incomplete_product_ids(conn) == [product_id]


def test_incomplete_includes_product_without_tag(conn_with_stores):
    conn = conn_with_stores
    product_id = _complete_product(conn, "1", "AGUA 500ML")
    products.remove_tag(conn, product_id, "mercearia")
    assert products.incomplete_product_ids(conn) == [product_id]


def test_incomplete_includes_un_product_without_content(conn_with_stores):
    conn = conn_with_stores
    product_id = _complete_product(conn, "1", "AGUA 500ML")
    products.clear_content(conn, product_id)
    _add_price(conn, product_id, "UN")
    assert products.incomplete_product_ids(conn) == [product_id]


def test_incomplete_excludes_kg_product_without_content(conn_with_stores):
    conn = conn_with_stores
    product_id = _complete_product(conn, "1", "TOMATE ITALIANO kg")
    products.clear_content(conn, product_id)
    _add_price(conn, product_id, "KG")
    assert products.incomplete_product_ids(conn) == []


def test_incomplete_includes_product_sold_by_un_in_any_store(conn_with_stores):
    conn = conn_with_stores
    product_id = _complete_product(conn, "1", "OVO BCO GRANDE C/30")
    products.clear_content(conn, product_id)
    _add_price(conn, product_id, "KG")
    _add_price(conn, product_id, "UN")
    assert products.incomplete_product_ids(conn) == [product_id]


def test_incomplete_excludes_complete_product(conn_with_stores):
    conn = conn_with_stores
    first = _complete_product(conn, "1", "AGUA 500ML")
    _add_price(conn, first, "UN")
    _complete_product(conn, "2", "TOMATE ITALIANO kg")
    assert products.incomplete_product_ids(conn) == []


def test_incomplete_is_ordered_by_id(conn_with_stores):
    conn = conn_with_stores
    for product_id in (3, 1, 2):
        conn.execute("INSERT INTO products (id, canonical_name) VALUES (?, ?)", (product_id, f"P{product_id}"))
    assert products.incomplete_product_ids(conn) == [1, 2, 3]


def test_sold_by_unit_ids(conn_with_stores):
    conn = conn_with_stores
    by_unit = products.resolve_product_id(conn, STORE_A, "1", "AGUA 500ML")
    by_weight = products.resolve_product_id(conn, STORE_A, "2", "TOMATE ITALIANO kg")
    _add_price(conn, by_unit, "UN")
    _add_price(conn, by_weight, "KG")
    assert products.sold_by_unit_ids(conn, [by_unit, by_weight, 999]) == {by_unit}
    assert products.sold_by_unit_ids(conn, []) == set()


def test_receipt_descriptions_returns_latest(conn_with_stores):
    conn = conn_with_stores
    product_id = products.resolve_product_id(conn, STORE_A, "1", "AGUA 500ML")
    _add_price(conn, product_id, "UN", "2026-09-05T16:50:34", "AGUA MIN 500ML ANTIGA")
    _add_price(conn, product_id, "UN", "2026-09-12T13:09:16", "AGUA MIN SF 500ML")
    assert products.receipt_descriptions(conn, [product_id]) == {product_id: "AGUA MIN SF 500ML"}


def test_receipt_descriptions_ignores_product_without_prices_and_empty_input(conn_with_stores):
    conn = conn_with_stores
    priced = products.resolve_product_id(conn, STORE_A, "1", "AGUA 500ML")
    unpriced = products.resolve_product_id(conn, STORE_A, "2", "TOMATE")
    _add_price(conn, priced, "UN", description="AGUA MIN SF 500ML")
    assert products.receipt_descriptions(conn, [priced, unpriced]) == {priced: "AGUA MIN SF 500ML"}
    assert products.receipt_descriptions(conn, []) == {}


def _three_products(conn) -> list[int]:
    return [products.resolve_product_id(conn, STORE_A, str(i), f"P{i}") for i in (1, 2, 3)]


def test_group_root_resolves_a_chain(conn_with_stores):
    conn = conn_with_stores
    a, b, c = _three_products(conn)
    products.set_merged_into(conn, a, b)
    products.set_merged_into(conn, b, c)
    assert [products.group_root(conn, pid) for pid in (a, b, c)] == [c, c, c]


def test_group_members_lists_root_and_absorbed_in_id_order(conn_with_stores):
    conn = conn_with_stores
    a, b, c = _three_products(conn)
    products.set_merged_into(conn, b, a)
    products.set_merged_into(conn, c, a)
    assert products.group_members(conn, a) == sorted([a, b, c])
    assert products.group_members(conn, c) == sorted([a, b, c])  # any member resolves to the group


def test_unmerging_the_middle_restores_the_previous_parent(conn_with_stores):
    """Why the column stores the direct target and not the root: otherwise the leaf would stay
    hanging on the root after the middle level is undone, and that is not the previous state."""
    conn = conn_with_stores
    a, b, c = _three_products(conn)
    products.set_merged_into(conn, a, b)
    products.set_merged_into(conn, b, c)
    products.set_merged_into(conn, b, None)
    assert products.group_root(conn, a) == b
    assert products.group_root(conn, c) == c


def test_group_of_an_unmerged_product_is_itself(conn_with_stores):
    conn = conn_with_stores
    pid = products.resolve_product_id(conn, STORE_A, "1", "P")
    assert products.group_root(conn, pid) == pid
    assert products.group_members(conn, pid) == [pid]


@pytest.mark.parametrize("call", [products.set_merged_into, products.group_root, products.group_members])
def test_group_functions_reject_unknown_product(conn, call):
    with pytest.raises(LookupError):
        call(conn, 999) if call is not products.set_merged_into else call(conn, 999, None)


def _merged_pair(conn, root_name="Raiz", absorbed_name="Absorvido"):
    root = products.resolve_product_id(conn, STORE_A, "100", root_name)
    absorbed = products.resolve_product_id(conn, STORE_A, "200", absorbed_name)
    products.set_merged_into(conn, absorbed, root)
    return root, absorbed


def test_get_product_inherits_content_from_absorbed(conn_with_stores):
    conn = conn_with_stores
    root, absorbed = _merged_pair(conn)
    products.set_content(conn, absorbed, 0.5, "KG")
    group = products.get_product(conn, root)
    assert (group.content_quantity, group.content_unit) == (0.5, "KG")

    products.set_merged_into(conn, absorbed, None)
    assert products.get_product(conn, root).content_quantity is None  # undo needs no reversal code


def test_get_product_inherits_kind_from_absorbed(conn_with_stores):
    conn = conn_with_stores
    root, absorbed = _merged_pair(conn)
    products.set_kind(conn, absorbed, "tomate")
    assert products.get_product(conn, root).kind == "tomate"


def test_get_product_keeps_root_value_when_both_have_one(conn_with_stores):
    conn = conn_with_stores
    root, absorbed = _merged_pair(conn)
    products.set_content(conn, root, 1.5, "L")
    products.set_content(conn, absorbed, 0.5, "L")
    products.set_kind(conn, root, "agua")
    products.set_kind(conn, absorbed, "refrigerante")
    group = products.get_product(conn, root)
    assert (group.content_quantity, group.kind) == (1.5, "agua")


def test_get_product_prefers_the_readable_name(conn_with_stores):
    conn = conn_with_stores
    root = products.resolve_product_id(conn, STORE_A, "100", "AGUA CRYSTAL 500ML")
    absorbed = products.resolve_product_id(conn, STORE_A, "200", "AGUA MIN CRYSTAL 500ML")
    for pid, description in ((root, "AGUA CRYSTAL 500ML"), (absorbed, "AGUA MIN CRYSTAL 500ML")):
        _add_price(conn, pid, "UN", description=description)
    products.rename_product(conn, absorbed, "Água Crystal 500ml")
    products.set_merged_into(conn, absorbed, root)
    assert products.get_product(conn, root).canonical_name == "Água Crystal 500ml"


def test_get_product_unions_tags(conn_with_stores):
    conn = conn_with_stores
    root, absorbed = _merged_pair(conn)
    products.add_tag(conn, root, "bebidas")
    products.add_tag(conn, absorbed, "mercearia")
    assert products.get_product(conn, root).tags == ("bebidas", "mercearia")


def test_get_product_resolves_any_member_to_the_group(conn_with_stores):
    conn = conn_with_stores
    root, absorbed = _merged_pair(conn)
    assert products.get_product(conn, absorbed) == products.get_product(conn, root)
    assert products.get_product(conn, absorbed).id == root


def test_list_products_and_names_hide_absorbed(conn_with_stores):
    conn = conn_with_stores
    root, absorbed = _merged_pair(conn)
    listed = products.list_products(conn)
    assert [product.id for product in listed] == [root]
    assert [pid for pid, _ in products.product_names(conn)] == [root]


def test_untagged_product_ids_uses_the_group(conn_with_stores):
    conn = conn_with_stores
    root, absorbed = _merged_pair(conn)
    assert products.untagged_product_ids(conn) == [root]
    products.add_tag(conn, absorbed, "bebidas")  # tagged through the absorbed product
    assert products.untagged_product_ids(conn) == []


def test_product_ids_with_tag_returns_the_root_once(conn_with_stores):
    conn = conn_with_stores
    root, absorbed = _merged_pair(conn)
    products.add_tag(conn, absorbed, "bebidas")
    assert products.product_ids_with_tag(conn, "bebidas") == [root]
    products.add_tag(conn, root, "bebidas")
    assert products.product_ids_with_tag(conn, "bebidas") == [root]


def test_has_raw_name_false_when_any_member_was_renamed(conn_with_stores):
    conn = conn_with_stores
    root = products.resolve_product_id(conn, STORE_A, "100", "AGUA CRYSTAL 500ML")
    absorbed = products.resolve_product_id(conn, STORE_A, "200", "AGUA MIN 500ML")
    for pid, description in ((root, "AGUA CRYSTAL 500ML"), (absorbed, "AGUA MIN 500ML")):
        _add_price(conn, pid, "UN", description=description)
    products.set_merged_into(conn, absorbed, root)
    assert products.has_raw_name(conn, root) is True
    products.rename_product(conn, absorbed, "Água Crystal 500ml")
    assert products.has_raw_name(conn, root) is False  # the group shows the hand-edited name


def test_incomplete_excludes_group_whose_absorbed_has_the_content(conn_with_stores):
    conn = conn_with_stores
    root, absorbed = _merged_pair(conn)
    products.add_tag(conn, root, "mercearia")
    products.set_kind(conn, root, "generico")
    _add_price(conn, root, "UN")
    assert products.incomplete_product_ids(conn) == [root]
    products.set_content(conn, absorbed, 1, "UN")
    assert products.incomplete_product_ids(conn) == []


def test_receipt_descriptions_and_sold_by_unit_cover_the_whole_group(conn_with_stores):
    conn = conn_with_stores
    root, absorbed = _merged_pair(conn)
    _add_price(conn, root, "KG", "2026-09-05T10:00:00", "RAIZ ANTIGA")
    _add_price(conn, absorbed, "UN", "2026-09-12T10:00:00", "ABSORVIDO RECENTE")
    assert products.sold_by_unit_ids(conn, [root]) == {root}
    assert products.receipt_descriptions(conn, [root]) == {root: "ABSORVIDO RECENTE"}
