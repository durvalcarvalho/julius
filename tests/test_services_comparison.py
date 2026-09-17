from julius.domain.models import Receipt, ReceiptItem
from julius.repositories.prices import insert_price
from julius.repositories.products import resolve_product_id, set_content, set_kind
from julius.repositories.stores import ensure_store
from julius.services.comparison import compare_stores, new_extremes

STORE_A = "00000000000001"
STORE_B = "00000000000002"


def _product(conn, name: str, code: str, store: str = STORE_A) -> int:
    ensure_store(conn, store, f"Loja {store[-1]}")
    return resolve_product_id(conn, store, code, name)


def _price(conn, product_id: int, store: str, unit: str, unit_price: float, purchased_at: str, key: str) -> None:
    receipt = Receipt(access_key=key, issued_at=purchased_at, store_cnpj=store, store_legal_name="S", items=())
    item = ReceiptItem(1, "c", "d", 1.0, unit, unit_price, unit_price)
    assert insert_price(conn, receipt, item, product_id)


def test_compare_stores_kg_group_two_stores(conn):
    a = _product(conn, "TOMATE ITALIANO kg", "1", STORE_A)
    b = _product(conn, "TOMATE ITALIANO UNIAO kg", "2", STORE_B)
    set_kind(conn, a, "tomate")
    set_kind(conn, b, "tomate")
    _price(conn, a, STORE_A, "KG", 11.89, "2026-09-16T10:00:00", "k1")
    _price(conn, b, STORE_B, "KG", 14.99, "2026-09-07T10:00:00", "k2")

    result = compare_stores(conn)

    (comparison,) = result.comparisons
    assert (comparison.kind, comparison.unit, comparison.basis) == ("tomate", "KG", "unit_price")
    assert [(entry.store_nickname, entry.price) for entry in comparison.entries] == [
        ("Loja 1", 11.89),
        ("Loja 2", 14.99),
    ]
    assert comparison.content_unit is None


def test_compare_stores_skips_single_store_group(conn):
    a = _product(conn, "BANANA kg", "1", STORE_A)
    set_kind(conn, a, "banana")
    _price(conn, a, STORE_A, "KG", 5.99, "2026-09-16T10:00:00", "k1")
    _price(conn, a, STORE_A, "KG", 4.99, "2026-09-10T10:00:00", "k2")

    assert compare_stores(conn).comparisons == ()


def test_compare_stores_uses_cheapest_per_store(conn):
    a = _product(conn, "UVA BRANCA", "1", STORE_A)
    b = _product(conn, "UVA GREEN DREAMS", "2", STORE_B)
    set_kind(conn, a, "uva")
    set_kind(conn, b, "uva")
    _price(conn, a, STORE_A, "KG", 14.99, "2026-09-16T10:00:00", "k1")
    _price(conn, a, STORE_A, "KG", 6.99, "2026-09-12T10:00:00", "k2")
    _price(conn, b, STORE_B, "KG", 9.99, "2026-09-07T10:00:00", "k3")

    (comparison,) = compare_stores(conn).comparisons

    assert comparison.entries[0].store_nickname == "Loja 1"
    assert comparison.entries[0].price == 6.99
    assert comparison.entries[0].purchased_at == "2026-09-12T10:00:00"


def test_compare_stores_un_group_uses_per_content(conn):
    small = _product(conn, "AGUA 500ML", "1", STORE_A)
    big = _product(conn, "AGUA 1,5L", "2", STORE_B)
    set_kind(conn, small, "água")
    set_kind(conn, big, "água")
    set_content(conn, small, 0.5, "L")
    set_content(conn, big, 1.5, "L")
    _price(conn, small, STORE_A, "UN", 1.49, "2026-09-16T10:00:00", "k1")
    _price(conn, big, STORE_B, "UN", 3.69, "2026-09-07T10:00:00", "k2")

    (comparison,) = compare_stores(conn).comparisons

    assert comparison.basis == "price_per_content"
    assert comparison.content_unit == "L"
    assert [entry.store_nickname for entry in comparison.entries] == ["Loja 2", "Loja 1"]


def test_compare_stores_skips_un_group_without_content(conn):
    small = _product(conn, "AGUA 500ML", "1", STORE_A)
    big = _product(conn, "AGUA 1,5L", "2", STORE_B)
    set_kind(conn, small, "água")
    set_kind(conn, big, "água")
    _price(conn, small, STORE_A, "UN", 1.49, "2026-09-16T10:00:00", "k1")
    _price(conn, big, STORE_B, "UN", 3.69, "2026-09-07T10:00:00", "k2")

    assert compare_stores(conn).comparisons == ()


def test_compare_stores_date_range_covers_used_observations(conn):
    a = _product(conn, "CEBOLA kg", "1", STORE_A)
    b = _product(conn, "CEBOLA BRANCA kg", "2", STORE_B)
    set_kind(conn, a, "cebola")
    set_kind(conn, b, "cebola")
    _price(conn, a, STORE_A, "KG", 7.89, "2026-09-16T10:00:00", "k1")
    _price(conn, a, STORE_A, "KG", 20.00, "2026-01-01T10:00:00", "k2")  # dearest, never the representative
    _price(conn, b, STORE_B, "KG", 9.99, "2026-09-07T10:00:00", "k3")

    result = compare_stores(conn)

    assert (result.first_purchase, result.last_purchase) == ("2026-09-07T10:00:00", "2026-09-16T10:00:00")


def test_compare_stores_empty_when_no_kinds(conn):
    a = _product(conn, "TOMATE kg", "1", STORE_A)
    _price(conn, a, STORE_A, "KG", 11.89, "2026-09-16T10:00:00", "k1")

    result = compare_stores(conn)

    assert (result.comparisons, result.first_purchase, result.last_purchase) == ((), "", "")


def test_compare_stores_deterministic_order(conn):
    tomato_a = _product(conn, "TOMATE kg", "1", STORE_A)
    tomato_b = _product(conn, "TOMATE ITALIANO kg", "2", STORE_B)
    onion_a = _product(conn, "CEBOLA kg", "3", STORE_A)
    onion_b = _product(conn, "CEBOLA BRANCA kg", "4", STORE_B)
    for product_id, kind in ((tomato_a, "tomate"), (tomato_b, "tomate"), (onion_a, "cebola"), (onion_b, "cebola")):
        set_kind(conn, product_id, kind)
    _price(conn, tomato_a, STORE_A, "KG", 10.0, "2026-09-16T10:00:00", "k1")
    _price(conn, tomato_b, STORE_B, "KG", 10.0, "2026-09-07T10:00:00", "k2")
    _price(conn, onion_a, STORE_A, "KG", 5.0, "2026-09-16T10:00:00", "k3")
    _price(conn, onion_b, STORE_B, "KG", 5.0, "2026-09-07T10:00:00", "k4")

    comparisons = compare_stores(conn).comparisons

    assert [comparison.kind for comparison in comparisons] == ["cebola", "tomate"]
    for comparison in comparisons:
        assert [entry.store_nickname for entry in comparison.entries] == ["Loja 1", "Loja 2"]


def test_compare_stores_ignores_untyped_products(conn):
    a = _product(conn, "ARROZ 5KG", "1", STORE_A)
    b = _product(conn, "ARROZ TIO 5KG", "2", STORE_B)
    _price(conn, a, STORE_A, "UN", 25.0, "2026-09-16T10:00:00", "k1")
    _price(conn, b, STORE_B, "UN", 27.0, "2026-09-07T10:00:00", "k2")

    assert compare_stores(conn).comparisons == ()


def test_compare_stores_ties_keep_the_newest_observation(conn):
    a = _product(conn, "TOMATE kg", "1", STORE_A)
    b = _product(conn, "TOMATE ITALIANO kg", "2", STORE_B)
    set_kind(conn, a, "tomate")
    set_kind(conn, b, "tomate")
    _price(conn, a, STORE_A, "KG", 10.0, "2026-09-01T10:00:00", "k1")
    _price(conn, a, STORE_A, "KG", 10.0, "2026-09-16T10:00:00", "k2")
    _price(conn, b, STORE_B, "KG", 12.0, "2026-09-07T10:00:00", "k3")

    (comparison,) = compare_stores(conn).comparisons

    assert comparison.entries[0].purchased_at == "2026-09-16T10:00:00"


def test_new_extremes_reports_new_low_across_stores(conn):
    old = _product(conn, "CEBOLA BRANCA kg", "1", STORE_B)
    new = _product(conn, "CEBOLA kg", "2", STORE_A)
    set_kind(conn, old, "cebola")
    set_kind(conn, new, "cebola")
    _price(conn, old, STORE_B, "KG", 9.99, "2026-09-07T10:00:00", "old")
    _price(conn, new, STORE_A, "KG", 7.89, "2026-09-16T10:00:00", "new")

    (extreme,) = new_extremes(conn, ["new"])

    assert extreme.highlight == "lowest"
    assert (extreme.price, extreme.previous_price) == (7.89, 9.99)
    assert (extreme.previous_store, extreme.scope) == ("Loja 2", "cebola")
    assert extreme.basis == "unit_price" and extreme.content_unit is None


def test_new_extremes_reports_new_high(conn):
    product = _product(conn, "MEL SILVES", "1", STORE_A)
    set_kind(conn, product, "mel")
    _price(conn, product, STORE_A, "UN", 29.99, "2026-09-04T10:00:00", "old")
    _price(conn, product, STORE_A, "UN", 33.99, "2026-09-16T10:00:00", "new")

    (extreme,) = new_extremes(conn, ["new"])

    assert extreme.highlight == "highest"
    assert (extreme.price, extreme.previous_price) == (33.99, 29.99)


def test_new_extremes_silent_without_history(conn):
    product = _product(conn, "NOVIDADE kg", "1", STORE_A)
    set_kind(conn, product, "novidade")
    _price(conn, product, STORE_A, "KG", 5.0, "2026-09-16T10:00:00", "new")

    assert new_extremes(conn, ["new"]) == []


def test_new_extremes_silent_when_price_in_between(conn):
    product = _product(conn, "CEBOLA kg", "1", STORE_A)
    _price(conn, product, STORE_A, "KG", 5.0, "2026-09-01T10:00:00", "a")
    _price(conn, product, STORE_A, "KG", 9.0, "2026-09-02T10:00:00", "b")
    _price(conn, product, STORE_A, "KG", 7.0, "2026-09-16T10:00:00", "new")

    assert new_extremes(conn, ["new"]) == []


def test_new_extremes_silent_when_tying_record(conn):
    product = _product(conn, "CEBOLA kg", "1", STORE_A)
    _price(conn, product, STORE_A, "KG", 5.0, "2026-09-01T10:00:00", "a")
    _price(conn, product, STORE_A, "KG", 5.0, "2026-09-16T10:00:00", "new")

    assert new_extremes(conn, ["new"]) == []


def test_new_extremes_excludes_own_receipt_from_history(conn):
    product = _product(conn, "CEBOLA kg", "1", STORE_A)
    _price(conn, product, STORE_A, "KG", 9.0, "2026-09-01T10:00:00", "old")
    receipt = Receipt(access_key="new", issued_at="2026-09-16T10:00:00", store_cnpj=STORE_A, store_legal_name="S", items=())
    for index, price in ((1, 5.0), (2, 6.0)):
        insert_price(conn, receipt, ReceiptItem(index, "c", "d", 1.0, "KG", price, price), product)

    extremes = new_extremes(conn, ["new"])

    # Both lines are measured against the 9.00 history, never against each other: if the 6.00 line
    # saw its own receipt's 5.00 as "previous", it would not be an extreme at all.
    assert sorted(extreme.price for extreme in extremes) == [5.0, 6.0]
    assert {extreme.previous_price for extreme in extremes} == {9.0}


def test_new_extremes_falls_back_to_product_scope_without_kind(conn):
    a = _product(conn, "CEBOLA kg", "1", STORE_A)
    b = _product(conn, "CEBOLA BRANCA kg", "2", STORE_B)
    _price(conn, b, STORE_B, "KG", 4.0, "2026-09-07T10:00:00", "other")
    _price(conn, a, STORE_A, "KG", 9.0, "2026-09-01T10:00:00", "old")
    _price(conn, a, STORE_A, "KG", 7.0, "2026-09-16T10:00:00", "new")

    (extreme,) = new_extremes(conn, ["new"])

    assert extreme.scope == "CEBOLA kg"
    assert extreme.previous_price == 9.0  # the other store's cheaper onion is out of scope


def test_new_extremes_uses_per_content_basis(conn):
    small = _product(conn, "AGUA 500ML", "1", STORE_A)
    big = _product(conn, "AGUA 1,5L", "2", STORE_B)
    set_kind(conn, small, "água")
    set_kind(conn, big, "água")
    set_content(conn, small, 0.5, "L")
    set_content(conn, big, 1.5, "L")
    _price(conn, small, STORE_A, "UN", 1.49, "2026-09-01T10:00:00", "old")
    _price(conn, big, STORE_B, "UN", 3.69, "2026-09-16T10:00:00", "new")

    (extreme,) = new_extremes(conn, ["new"])

    assert extreme.basis == "price_per_content"
    assert extreme.content_unit == "L"
    assert extreme.highlight == "lowest"
    assert extreme.price == 3.69 / 1.5


def test_new_extremes_skips_non_participating_item(conn):
    small = _product(conn, "AGUA 500ML", "1", STORE_A)
    big = _product(conn, "AGUA 1,5L", "2", STORE_B)
    set_kind(conn, small, "água")
    set_kind(conn, big, "água")
    _price(conn, big, STORE_B, "UN", 3.69, "2026-09-01T10:00:00", "old")
    _price(conn, small, STORE_A, "UN", 1.49, "2026-09-16T10:00:00", "new")

    assert new_extremes(conn, ["new"]) == []


def test_new_extremes_orders_lowest_first_then_by_magnitude(conn):
    small_drop = _product(conn, "ARROZ kg", "1", STORE_A)
    big_drop = _product(conn, "FEIJAO kg", "2", STORE_A)
    rise = _product(conn, "ACUCAR kg", "3", STORE_A)
    for product_id, old_price, new_price in ((small_drop, 10.0, 9.0), (big_drop, 10.0, 5.0), (rise, 10.0, 20.0)):
        _price(conn, product_id, STORE_A, "KG", old_price, "2026-09-01T10:00:00", f"old{product_id}")
    receipt = Receipt(access_key="new", issued_at="2026-09-16T10:00:00", store_cnpj=STORE_A, store_legal_name="S", items=())
    for index, (product_id, price) in enumerate([(small_drop, 9.0), (big_drop, 5.0), (rise, 20.0)], start=1):
        insert_price(conn, receipt, ReceiptItem(index, "c", "d", 1.0, "KG", price, price), product_id)

    extremes = new_extremes(conn, ["new"])

    assert [extreme.product_name for extreme in extremes] == ["FEIJAO kg", "ARROZ kg", "ACUCAR kg"]


def test_new_extremes_empty_access_keys(conn):
    product = _product(conn, "CEBOLA kg", "1", STORE_A)
    _price(conn, product, STORE_A, "KG", 5.0, "2026-09-16T10:00:00", "new")
    assert new_extremes(conn, []) == []
    assert new_extremes(conn, ["inexistente"]) == []


def test_compare_stores_keeps_two_branches_that_share_a_nickname(conn):
    """Two CNPJs of one chain are two stores. They share a nickname until the user renames them,
    and keying the group by nickname collapsed them into one — dropping the group as single-store
    (measured on the real database: 6 groups had two CNPJs, only 5 survived)."""
    branch_a, branch_b = "11832478000285", "11832478000366"
    ensure_store(conn, branch_a, "Dona de Casa")
    ensure_store(conn, branch_b, "Dona de Casa")
    a = resolve_product_id(conn, branch_a, "1", "SACOLA REUTILIZAVEL UND")
    b = resolve_product_id(conn, branch_b, "2", "SACOLA REUTILIZAVEL UND")
    for product_id in (a, b):
        set_kind(conn, product_id, "sacola reutilizável")
        set_content(conn, product_id, 1.0, "UN")
    _price(conn, a, branch_a, "UN", 0.22, "2026-09-07T10:00:00", "k1")
    _price(conn, b, branch_b, "UN", 0.30, "2026-09-10T10:00:00", "k2")

    (comparison,) = compare_stores(conn).comparisons

    assert [(entry.store_cnpj, entry.price) for entry in comparison.entries] == [
        (branch_a, 0.22),
        (branch_b, 0.30),
    ]
    assert {entry.store_nickname for entry in comparison.entries} == {"Dona de Casa"}
