from julius.domain.models import Receipt, ReceiptItem
from julius.repositories.prices import insert_price
from julius.repositories.products import resolve_product_id, set_content, set_kind
from julius.repositories.stores import ensure_store
from julius.services.comparison import (
    PLAUSIBLE_QTY_MAX,
    PLAUSIBLE_QTY_MIN,
    WORTH_IT_THRESHOLD_REAIS,
    check_price,
    compare_stores,
    new_extremes,
    shopping_verdict,
)

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


def test_compare_stores_names_the_product_behind_each_price(conn):
    """The group label is a kind, so two stores can be represented by different products: the
    wine group compared a frisante with a Norton and the table said only "vinho"."""
    a = _product(conn, "VINHO MIORANZA FRISANTE 750ML", "1", STORE_A)
    b = _product(conn, "VH NORTON 750 BC SV", "2", STORE_B)
    for product_id in (a, b):
        set_kind(conn, product_id, "vinho")
        set_content(conn, product_id, 0.75, "L")
    _price(conn, a, STORE_A, "UN", 23.99, "2026-09-16T10:00:00", "k1")
    _price(conn, b, STORE_B, "UN", 34.90, "2026-09-04T10:00:00", "k2")

    (comparison,) = compare_stores(conn).comparisons

    assert [entry.product_name for entry in comparison.entries] == [
        "VINHO MIORANZA FRISANTE 750ML",
        "VH NORTON 750 BC SV",
    ]


def test_compare_stores_names_the_cheapest_product_of_that_store(conn):
    """A store is represented by the cheapest row it charged in the group. With two products in
    one store, the name has to follow the price that won the slot, not the first row seen."""
    cheap = _product(conn, "UVA VITORIA BANDEJA 500G", "1", STORE_A)
    dear = _product(conn, "UVA GREEN DREAMS BANDEJA 500G", "2", STORE_A)
    other = _product(conn, "UVA BRANCA BANDEJA 500G", "3", STORE_B)
    for product_id in (cheap, dear, other):
        set_kind(conn, product_id, "uva")
        set_content(conn, product_id, 0.5, "KG")
    _price(conn, dear, STORE_A, "UN", 14.99, "2026-09-16T10:00:00", "k1")
    _price(conn, cheap, STORE_A, "UN", 5.95, "2026-09-16T11:00:00", "k2")
    _price(conn, other, STORE_B, "UN", 6.99, "2026-09-04T10:00:00", "k3")

    (comparison,) = compare_stores(conn).comparisons

    store_a = next(entry for entry in comparison.entries if entry.store_nickname == "Loja 1")
    assert store_a.product_name == "UVA VITORIA BANDEJA 500G"


def test_new_extremes_names_the_product_that_was_beaten(conn):
    """Within a kind, the record can belong to another product — that is the whole reason the
    signal needs the name: "menor preço já pago" over `vinho` compared two different wines."""
    a = _product(conn, "VINHO MIORANZA FRISANTE 750ML", "1", STORE_A)
    b = _product(conn, "VH NORTON 750 BC SV", "2", STORE_B)
    for product_id in (a, b):
        set_kind(conn, product_id, "vinho")
        set_content(conn, product_id, 0.75, "L")
    _price(conn, b, STORE_B, "UN", 34.90, "2026-09-04T10:00:00", "old")
    _price(conn, a, STORE_A, "UN", 23.99, "2026-09-16T10:00:00", "new")

    (extreme,) = new_extremes(conn, ["new"])

    assert extreme.product_name == "VINHO MIORANZA FRISANTE 750ML"
    assert extreme.previous_product_name == "VH NORTON 750 BC SV"


def test_compare_stores_kinds_filters_groups(conn):
    tomato_a = _product(conn, "TOMATE kg", "1", STORE_A)
    tomato_b = _product(conn, "TOMATE ITALIANO kg", "2", STORE_B)
    onion_a = _product(conn, "CEBOLA kg", "3", STORE_A)
    onion_b = _product(conn, "CEBOLA BRANCA kg", "4", STORE_B)
    for product_id, kind in ((tomato_a, "tomate"), (tomato_b, "tomate"), (onion_a, "cebola"), (onion_b, "cebola")):
        set_kind(conn, product_id, kind)
    _price(conn, tomato_a, STORE_A, "KG", 10.0, "2026-09-16T10:00:00", "k1")
    _price(conn, tomato_b, STORE_B, "KG", 12.0, "2026-09-07T10:00:00", "k2")
    _price(conn, onion_a, STORE_A, "KG", 5.0, "2026-09-16T10:00:00", "k3")
    _price(conn, onion_b, STORE_B, "KG", 6.0, "2026-09-07T10:00:00", "k4")

    filtered = compare_stores(conn, kinds=["tomate"])
    unfiltered = compare_stores(conn)

    assert [comparison.kind for comparison in filtered.comparisons] == ["tomate"]
    assert [comparison.kind for comparison in unfiltered.comparisons] == ["cebola", "tomate"]


def test_compare_stores_kinds_none_and_omitted_are_same_as_today(conn):
    a = _product(conn, "TOMATE ITALIANO kg", "1", STORE_A)
    b = _product(conn, "TOMATE ITALIANO UNIAO kg", "2", STORE_B)
    set_kind(conn, a, "tomate")
    set_kind(conn, b, "tomate")
    _price(conn, a, STORE_A, "KG", 11.89, "2026-09-16T10:00:00", "k1")
    _price(conn, b, STORE_B, "KG", 14.99, "2026-09-07T10:00:00", "k2")

    assert compare_stores(conn, kinds=None) == compare_stores(conn)
    assert compare_stores(conn, kinds=()) == compare_stores(conn)


def test_shopping_verdict_empty_comparison_is_none():
    from julius.domain.models import StoreComparison

    assert shopping_verdict(StoreComparison((), "", "")) is None


def test_shopping_verdict_single_winner(conn):
    tomato_a = _product(conn, "TOMATE kg", "1", STORE_A)
    tomato_b = _product(conn, "TOMATE ITALIANO kg", "2", STORE_B)
    onion_a = _product(conn, "CEBOLA kg", "3", STORE_A)
    onion_b = _product(conn, "CEBOLA BRANCA kg", "4", STORE_B)
    grape_a = _product(conn, "UVA BRANCA", "5", STORE_A)
    grape_b = _product(conn, "UVA VERDE", "6", STORE_B)
    for product_id, kind in (
        (tomato_a, "tomate"),
        (tomato_b, "tomate"),
        (onion_a, "cebola"),
        (onion_b, "cebola"),
        (grape_a, "uva"),
        (grape_b, "uva"),
    ):
        set_kind(conn, product_id, kind)
    _price(conn, tomato_a, STORE_A, "KG", 10.0, "2026-09-16T10:00:00", "k1")
    _price(conn, tomato_b, STORE_B, "KG", 12.0, "2026-09-07T10:00:00", "k2")
    _price(conn, onion_a, STORE_A, "KG", 5.0, "2026-09-16T10:00:00", "k3")
    _price(conn, onion_b, STORE_B, "KG", 6.0, "2026-09-07T10:00:00", "k4")
    _price(conn, grape_a, STORE_A, "KG", 20.0, "2026-09-16T10:00:00", "k5")
    _price(conn, grape_b, STORE_B, "KG", 15.0, "2026-09-07T10:00:00", "k6")

    verdict = shopping_verdict(compare_stores(conn))

    assert verdict.total_items == 3
    assert verdict.winner_stores == ("Loja 1",)
    assert set(verdict.won_kinds) == {"cebola", "tomate"}
    assert verdict.runner_up_store == "Loja 2"
    assert verdict.runner_up_kinds == ("uva",)


def test_shopping_verdict_tie_at_top_names_both(conn):
    tomato_a = _product(conn, "TOMATE kg", "1", STORE_A)
    tomato_b = _product(conn, "TOMATE ITALIANO kg", "2", STORE_B)
    onion_a = _product(conn, "CEBOLA kg", "3", STORE_A)
    onion_b = _product(conn, "CEBOLA BRANCA kg", "4", STORE_B)
    for product_id, kind in ((tomato_a, "tomate"), (tomato_b, "tomate"), (onion_a, "cebola"), (onion_b, "cebola")):
        set_kind(conn, product_id, kind)
    _price(conn, tomato_a, STORE_A, "KG", 10.0, "2026-09-16T10:00:00", "k1")
    _price(conn, tomato_b, STORE_B, "KG", 12.0, "2026-09-07T10:00:00", "k2")
    _price(conn, onion_b, STORE_B, "KG", 5.0, "2026-09-16T10:00:00", "k3")
    _price(conn, onion_a, STORE_A, "KG", 6.0, "2026-09-07T10:00:00", "k4")

    verdict = shopping_verdict(compare_stores(conn))

    assert verdict.winner_stores == ("Loja 1", "Loja 2")
    assert verdict.runner_up_store is None
    assert verdict.runner_up_kinds == ()


def test_shopping_verdict_winner_sweeps_everything(conn):
    tomato_a = _product(conn, "TOMATE kg", "1", STORE_A)
    tomato_b = _product(conn, "TOMATE ITALIANO kg", "2", STORE_B)
    onion_a = _product(conn, "CEBOLA kg", "3", STORE_A)
    onion_b = _product(conn, "CEBOLA BRANCA kg", "4", STORE_B)
    for product_id, kind in ((tomato_a, "tomate"), (tomato_b, "tomate"), (onion_a, "cebola"), (onion_b, "cebola")):
        set_kind(conn, product_id, kind)
    _price(conn, tomato_a, STORE_A, "KG", 10.0, "2026-09-16T10:00:00", "k1")
    _price(conn, tomato_b, STORE_B, "KG", 12.0, "2026-09-07T10:00:00", "k2")
    _price(conn, onion_a, STORE_A, "KG", 5.0, "2026-09-16T10:00:00", "k3")
    _price(conn, onion_b, STORE_B, "KG", 6.0, "2026-09-07T10:00:00", "k4")

    verdict = shopping_verdict(compare_stores(conn))

    assert verdict.runner_up_store is None
    assert verdict.runner_up_kinds == ()


def test_shopping_verdict_uses_cnpj_not_nickname_for_tally(conn):
    branch_a, branch_b = "11832478000285", "11832478000366"
    ensure_store(conn, branch_a, "Dona de Casa")
    ensure_store(conn, branch_b, "Dona de Casa")
    ensure_store(conn, STORE_B, "Loja 2")
    tomato_a = resolve_product_id(conn, branch_a, "1", "TOMATE kg")
    tomato_b = resolve_product_id(conn, STORE_B, "2", "TOMATE ITALIANO kg")
    onion_a = resolve_product_id(conn, branch_b, "3", "CEBOLA kg")
    onion_b = resolve_product_id(conn, STORE_B, "4", "CEBOLA BRANCA kg")
    for product_id, kind in ((tomato_a, "tomate"), (tomato_b, "tomate"), (onion_a, "cebola"), (onion_b, "cebola")):
        set_kind(conn, product_id, kind)
    _price(conn, tomato_a, branch_a, "KG", 5.0, "2026-09-16T10:00:00", "k1")
    _price(conn, tomato_b, STORE_B, "KG", 12.0, "2026-09-07T10:00:00", "k2")
    _price(conn, onion_a, branch_b, "KG", 5.0, "2026-09-16T10:00:00", "k3")
    _price(conn, onion_b, STORE_B, "KG", 12.0, "2026-09-07T10:00:00", "k4")

    verdict = shopping_verdict(compare_stores(conn))

    # Both "Dona de Casa" branches win one group each -- tallied separately by CNPJ, they tie with
    # STORE_B (0 wins) losing outright, not summed into a single 2-win "Dona de Casa".
    assert verdict.winner_stores == (f"Dona de Casa · {branch_a}", f"Dona de Casa · {branch_b}")


def test_shopping_verdict_category_of_none_is_unchanged(conn):
    """Pin: the default keeps the exact behaviour every caller before Decisão 5 already had --
    `julius mercados comparar` (CLI) never passes `category_of` and must never see this change."""
    tomato_a = _product(conn, "TOMATE kg", "1", STORE_A)
    tomato_b = _product(conn, "TOMATE ITALIANO kg", "2", STORE_B)
    set_kind(conn, tomato_a, "tomate")
    set_kind(conn, tomato_b, "tomate")
    _price(conn, tomato_a, STORE_A, "KG", 10.0, "2026-09-16T10:00:00", "k1")
    _price(conn, tomato_b, STORE_B, "KG", 12.0, "2026-09-07T10:00:00", "k2")

    comparison = compare_stores(conn)
    assert shopping_verdict(comparison, category_of=None) == shopping_verdict(comparison)


def test_shopping_verdict_by_category_never_splits_one_category_between_two_stores(conn):
    """RF6 (docs/requirements/shopping-verdict-shape.md): tomate and cebola are both "hortifruti"
    -- per-kind alone would send tomate to Loja 1 and cebola to Loja 2 (a real split of the same
    aisle across two markets). Grouped by category, cebola follows the category's own winner."""
    tomato_a = _product(conn, "TOMATE kg", "1", STORE_A)
    tomato_b = _product(conn, "TOMATE ITALIANO kg", "2", STORE_B)
    onion_a = _product(conn, "CEBOLA kg", "3", STORE_A)
    onion_b = _product(conn, "CEBOLA BRANCA kg", "4", STORE_B)
    detergent_a = _product(conn, "DETERGENTE", "5", STORE_A)
    detergent_b = _product(conn, "DETERGENTE NEUTRO", "6", STORE_B)
    for product_id, kind in (
        (tomato_a, "tomate"),
        (tomato_b, "tomate"),
        (onion_a, "cebola"),
        (onion_b, "cebola"),
        (detergent_a, "desengordurante"),
        (detergent_b, "desengordurante"),
    ):
        set_kind(conn, product_id, kind)
    _price(conn, tomato_a, STORE_A, "KG", 10.0, "2026-09-16T10:00:00", "k1")  # tomate: Loja 1 wins
    _price(conn, tomato_b, STORE_B, "KG", 12.0, "2026-09-07T10:00:00", "k2")
    _price(conn, onion_b, STORE_B, "KG", 5.0, "2026-09-16T10:00:00", "k3")  # cebola: Loja 2 wins (raw)
    _price(conn, onion_a, STORE_A, "KG", 6.0, "2026-09-07T10:00:00", "k4")
    _price(conn, detergent_b, STORE_B, "KG", 4.0, "2026-09-16T10:00:00", "k5")  # desengordurante: Loja 2 wins
    _price(conn, detergent_a, STORE_A, "KG", 5.0, "2026-09-07T10:00:00", "k6")
    comparison = compare_stores(conn)

    # Confirms the premise: per kind alone, tomate and cebola really do have different winners --
    # this is the split RF6 exists to prevent once they share a category.
    raw_winner = {group.kind: group.entries[0].store_cnpj for group in comparison.comparisons}
    assert raw_winner["tomate"] != raw_winner["cebola"]

    category_of = {"tomate": "hortifruti", "cebola": "hortifruti", "desengordurante": "limpeza"}
    grouped = shopping_verdict(comparison, category_of=category_of)

    assert grouped.winner_stores == ("Loja 1",)
    assert set(grouped.won_kinds) == {"tomate", "cebola"}  # cebola no longer split off to Loja 2
    assert grouped.runner_up_store == "Loja 2"
    assert grouped.runner_up_kinds == ("desengordurante",)


def test_shopping_verdict_by_category_caps_at_two_stores(conn):
    """3 categories, 3 different raw winners -- capped to the 2 stores covering the most kinds;
    the 3rd store's category is reassigned to a finalist, never left pointing at a 3rd market."""
    STORE_C = "00000000000003"
    tomato_a = _product(conn, "TOMATE kg", "1", STORE_A)
    tomato_b = _product(conn, "TOMATE ITALIANO kg", "2", STORE_B)
    onion_a = _product(conn, "CEBOLA kg", "3", STORE_A)
    onion_b = _product(conn, "CEBOLA BRANCA kg", "4", STORE_B)
    carrot_a = _product(conn, "CENOURA kg", "5", STORE_A)
    carrot_b = _product(conn, "CENOURA BABY kg", "6", STORE_B)
    detergent_b = _product(conn, "DETERGENTE", "7", STORE_B)
    detergent_c = _product(conn, "DETERGENTE NEUTRO", "8", STORE_C)
    soap_b = _product(conn, "SABAO EM PO", "9", STORE_B)
    soap_c = _product(conn, "SABAO EM PO NEUTRO", "10", STORE_C)
    juice_a = _product(conn, "SUCO DE UVA", "11", STORE_A)
    juice_c = _product(conn, "SUCO DE LARANJA", "12", STORE_C)
    for product_id, kind in (
        (tomato_a, "tomate"),
        (tomato_b, "tomate"),
        (onion_a, "cebola"),
        (onion_b, "cebola"),
        (carrot_a, "cenoura"),
        (carrot_b, "cenoura"),
        (detergent_b, "desengordurante"),
        (detergent_c, "desengordurante"),
        (soap_b, "sabão em pó"),
        (soap_c, "sabão em pó"),
        (juice_a, "suco"),
        (juice_c, "suco"),
    ):
        set_kind(conn, product_id, kind)
    # hortifruti: Loja 1 wins all 3 kinds
    _price(conn, tomato_a, STORE_A, "KG", 10.0, "2026-09-16T10:00:00", "k1")
    _price(conn, tomato_b, STORE_B, "KG", 12.0, "2026-09-07T10:00:00", "k2")
    _price(conn, onion_a, STORE_A, "KG", 5.0, "2026-09-16T10:00:00", "k3")
    _price(conn, onion_b, STORE_B, "KG", 6.0, "2026-09-07T10:00:00", "k4")
    _price(conn, carrot_a, STORE_A, "KG", 3.0, "2026-09-16T10:00:00", "k5")
    _price(conn, carrot_b, STORE_B, "KG", 4.0, "2026-09-07T10:00:00", "k6")
    # limpeza: Loja 2 wins both kinds
    _price(conn, detergent_b, STORE_B, "KG", 4.0, "2026-09-16T10:00:00", "k7")
    _price(conn, detergent_c, STORE_C, "KG", 5.0, "2026-09-07T10:00:00", "k8")
    _price(conn, soap_b, STORE_B, "KG", 8.0, "2026-09-16T10:00:00", "k9")
    _price(conn, soap_c, STORE_C, "KG", 9.0, "2026-09-07T10:00:00", "k10")
    # bebidas: Loja 3 wins its only kind
    _price(conn, juice_c, STORE_C, "KG", 9.0, "2026-09-16T10:00:00", "k11")
    _price(conn, juice_a, STORE_A, "KG", 12.0, "2026-09-07T10:00:00", "k12")
    comparison = compare_stores(conn)
    category_of = {
        "tomate": "hortifruti",
        "cebola": "hortifruti",
        "cenoura": "hortifruti",
        "desengordurante": "limpeza",
        "sabão em pó": "limpeza",
        "suco": "bebidas",
    }

    verdict = shopping_verdict(comparison, category_of=category_of)

    stores_named = {verdict.winner_stores[0], verdict.runner_up_store}
    assert "Loja 3" not in stores_named, "the 3rd market must never be recommended when capped to 2"
    assert verdict.winner_stores == ("Loja 1",)
    assert set(verdict.won_kinds) == {"tomate", "cebola", "cenoura", "suco"}
    assert verdict.runner_up_store == "Loja 2"
    assert verdict.runner_up_kinds == ("desengordurante", "sabão em pó")


def test_check_price_no_history_for_the_kind(conn):
    result = check_price(conn, "tomate", 9.99)

    assert result.verdict is None
    assert result.reason == "no_history"
    assert result.kind == "tomate"
    assert result.reference_price is None


def test_check_price_ambiguous_unit_never_guesses(conn):
    """Real case measured against production: "tomate" has both loose tomatoes by KG and a
    packaged combo by UN -- the check must ask, never silently pick one."""
    loose = _product(conn, "TOMATE ITALIANO kg", "1", STORE_A)
    packaged = _product(conn, "TOMATE TREBESCHI 250G DUO", "2", STORE_A)
    set_kind(conn, loose, "tomate")
    set_kind(conn, packaged, "tomate")
    _price(conn, loose, STORE_A, "KG", 11.89, "2026-09-16T10:00:00", "k1")
    _price(conn, packaged, STORE_A, "UN", 9.90, "2026-09-07T10:00:00", "k2")

    result = check_price(conn, "tomate", 12.0)

    assert result.reason == "ambiguous_unit"
    assert result.verdict is None


def test_check_price_no_comparable_basis_is_not_mislabeled_as_no_history(conn):
    """Two different UN products, no content declared -- `comparison_basis` finds nothing
    comparable (same rule that drops these groups from `compare_stores` entirely). There IS
    history here; it just cannot be compared yet, so this must not read as "no_history"."""
    a = _product(conn, "DETERGENTE", "1", STORE_A)
    b = _product(conn, "DETERGENTE NEUTRO", "2", STORE_B)
    set_kind(conn, a, "desengordurante")
    set_kind(conn, b, "desengordurante")
    _price(conn, a, STORE_A, "UN", 4.0, "2026-09-16T10:00:00", "k1")
    _price(conn, b, STORE_B, "UN", 5.0, "2026-09-07T10:00:00", "k2")

    result = check_price(conn, "desengordurante", 4.5)

    assert result.reason == "no_comparable_basis"
    assert result.verdict is None


def test_check_price_within_tolerance_is_a_yes(conn):
    # Two different boxes of the same content (30 UN each) -- comparable by price-per-content,
    # same rule `comparison_basis` already applies everywhere else in this project.
    a = _product(conn, "OVO A", "1", STORE_A)
    b = _product(conn, "OVO B", "2", STORE_B)
    set_kind(conn, a, "ovo")
    set_kind(conn, b, "ovo")
    set_content(conn, a, 30, "UN")
    set_content(conn, b, 30, "UN")
    _price(conn, a, STORE_A, "UN", 0.53 * 30, "2026-09-16T10:00:00", "k1")
    _price(conn, b, STORE_B, "UN", 0.57 * 30, "2026-09-07T10:00:00", "k2")

    result = check_price(conn, "ovo", 0.59)  # ~11.3% over 0.53, the user's own "tá bom" example

    assert result.verdict is True
    assert result.reference_price == 0.53
    assert result.reference_unit == "UN"  # content_unit, since basis is price_per_content here
    assert result.reference_store == "Loja 1"
    assert round(result.diff_pct, 1) == round((0.59 - 0.53) / 0.53 * 100, 1)


def test_check_price_small_absolute_gap_is_a_yes_even_at_high_percent(conn):
    """Deliberate reversal, documented in docs/design/quantity-aware-verdict.md, Decisão 1: this
    used to be the user's own "bem mais caro" example under the old percentage-only gate (~41.5%
    over 0.53). Under the R$ gate, the gap (R$0,22) times PLAUSIBLE_QTY_MAX never clears
    WORTH_IT_THRESHOLD_REAIS -- a few dozen eggs is still just a few reais. Not a bug: RF5 of
    docs/requirements/quantity-aware-verdict.md says a small absolute gap never changes the
    answer, whatever the percentage."""
    a = _product(conn, "OVO A", "1", STORE_A)
    b = _product(conn, "OVO B", "2", STORE_B)
    set_kind(conn, a, "ovo")
    set_kind(conn, b, "ovo")
    set_content(conn, a, 30, "UN")
    set_content(conn, b, 30, "UN")
    _price(conn, a, STORE_A, "UN", 0.53 * 30, "2026-09-16T10:00:00", "k1")
    _price(conn, b, STORE_B, "UN", 0.55 * 30, "2026-09-07T10:00:00", "k2")

    result = check_price(conn, "ovo", 0.75)

    assert result.verdict is True
    assert result.reason is None


def test_check_price_cheaper_than_reference_is_a_yes(conn):
    a = _product(conn, "OVO A", "1", STORE_A)
    b = _product(conn, "OVO B", "2", STORE_B)
    set_kind(conn, a, "ovo")
    set_kind(conn, b, "ovo")
    set_content(conn, a, 30, "UN")
    set_content(conn, b, 30, "UN")
    _price(conn, a, STORE_A, "UN", 0.53 * 30, "2026-09-16T10:00:00", "k1")
    _price(conn, b, STORE_B, "UN", 0.60 * 30, "2026-09-07T10:00:00", "k2")

    result = check_price(conn, "ovo", 0.40)

    assert result.verdict is True
    assert result.diff_pct < 0


def test_check_price_gate_constants_are_positive_and_ordered():
    assert WORTH_IT_THRESHOLD_REAIS > 0
    assert 0 < PLAUSIBLE_QTY_MIN < PLAUSIBLE_QTY_MAX


def test_check_price_trivial_gap_never_asks_even_at_high_percent(conn):
    """The measured case that decided the whole design (docs/design/quantity-aware-verdict.md):
    sacola reutilizável, 10% of difference but R$0,02 -- never worth asking, whatever the
    quantity."""
    a = _product(conn, "SACOLA REUTILIZAVEL UND", "1", STORE_A)
    set_kind(conn, a, "sacola reutilizável")
    set_content(conn, a, 1, "UN")
    _price(conn, a, STORE_A, "UN", 0.20, "2026-09-16T10:00:00", "k1")

    result = check_price(conn, "sacola reutilizável", 0.22)

    assert result.verdict is True
    assert result.reason is None


def test_check_price_huge_gap_skips_straight_to_no(conn):
    """Gap large enough that even PLAUSIBLE_QTY_MIN already clears the threshold -- decided
    without asking quantity at all."""
    a = _product(conn, "ITEM CARO", "1", STORE_A)
    set_kind(conn, a, "item raro")
    _price(conn, a, STORE_A, "KG", 10.0, "2026-09-16T10:00:00", "k1")

    result = check_price(conn, "item raro", 100.0)  # gap = 90, well above WORTH_IT_THRESHOLD_REAIS / QTY_MIN

    assert result.verdict is False
    assert result.reason is None


def test_check_price_middle_gap_without_quantity_asks(conn):
    """The user's own example: acém at R$40 against a R$35 reference (gap R$5,00) -- doesn't
    settle at either extreme, so it comes back asking, with every other fact already filled in."""
    a = _product(conn, "ACEM BOVINO", "1", STORE_A)
    set_kind(conn, a, "acém")
    _price(conn, a, STORE_A, "KG", 35.0, "2026-09-16T10:00:00", "k1")

    result = check_price(conn, "acém", 40.0)

    assert result.verdict is None
    assert result.reason == "quantity_needed"
    assert result.reference_price == 35.0
    assert result.reference_store == "Loja 1"
    assert result.diff_pct is not None


def test_check_price_middle_gap_small_quantity_is_a_yes(conn):
    """A small purchase (1kg) means the R$5,00/kg gap totals R$5,00 -- trivial, not worth chasing
    another market for it. verdict=True means "tá bom, pode levar aqui" (same polarity as
    price_check_fallback_line's "Sim, vale a pena."), not "vale trocar de mercado"."""
    a = _product(conn, "ACEM BOVINO", "1", STORE_A)
    set_kind(conn, a, "acém")
    _price(conn, a, STORE_A, "KG", 35.0, "2026-09-16T10:00:00", "k1")

    result = check_price(conn, "acém", 40.0, quantity=1.0)

    assert result.verdict is True
    assert result.reason is None


def test_check_price_middle_gap_large_quantity_is_a_no(conn):
    """The same R$5,00/kg gap over 14kg (the user's "compra do mês") totals R$70,00 -- real money,
    verdict=False, "não, tá caro" (go to the cheaper market instead)."""
    a = _product(conn, "ACEM BOVINO", "1", STORE_A)
    set_kind(conn, a, "acém")
    _price(conn, a, STORE_A, "KG", 35.0, "2026-09-16T10:00:00", "k1")

    result = check_price(conn, "acém", 40.0, quantity=14.0)

    assert result.verdict is False
    assert result.reason is None


def test_new_extremes_repeats_the_name_when_a_product_beats_itself(conn):
    """The common case: same product, cheaper than last time. The CLI suppresses the repetition
    (see test_cli_receipts), so the service must still report it rather than blank it out."""
    a = _product(conn, "CEBOLA kg", "1", STORE_A)
    set_kind(conn, a, "cebola")
    _price(conn, a, STORE_A, "KG", 9.99, "2026-09-04T10:00:00", "old")
    _price(conn, a, STORE_A, "KG", 7.89, "2026-09-16T10:00:00", "new")

    (extreme,) = new_extremes(conn, ["new"])

    assert extreme.previous_product_name == extreme.product_name == "CEBOLA kg"
