from pathlib import Path

import pytest

from julius.domain.models import Receipt, ReceiptItem
from julius.parsers.df import DFReceiptParser
from julius.repositories.prices import insert_price
from julius.repositories.products import add_tag, product_names, resolve_product_id
from julius.repositories.stores import ensure_store
from julius.services.search import catalog_for_matching, closest_names, records_for_products, search_prices

FIXTURES_DIR = Path(__file__).parent / "fixtures"
STORE = "00000000000001"


def _import(conn, fixture_name: str) -> None:
    receipt = DFReceiptParser().parse((FIXTURES_DIR / fixture_name).read_text(encoding="utf-8"), fixture_name)
    ensure_store(conn, receipt.store_cnpj, receipt.store_legal_name)
    for item in receipt.items:
        product_id = resolve_product_id(conn, receipt.store_cnpj, item.product_code, item.description)
        insert_price(conn, receipt, item, product_id)
    conn.commit()


def _product(conn, name: str, code: str) -> int:
    ensure_store(conn, STORE, "Synthetic store")
    return resolve_product_id(conn, STORE, code, name)


def _price(conn, product_id: int, unit: str, unit_price: float, purchased_at: str, key: str) -> None:
    receipt = Receipt(access_key=key, issued_at=purchased_at, store_cnpj=STORE, store_legal_name="S", items=())
    item = ReceiptItem(1, "c", "d", 1.0, unit, unit_price, unit_price)
    assert insert_price(conn, receipt, item, product_id)


def _id_of(conn, name_fragment: str) -> int:
    return next(product_id for product_id, name in product_names(conn) if name_fragment in name)


def test_exact_term_returns_all_rows_of_that_product(conn):
    _import(conn, "qrcode.html")
    rows = search_prices(conn, "picanha")
    assert len(rows) == 3
    assert {row.unit for row in rows} == {"KG"}
    assert len({row.product_id for row in rows}) == 1


def test_typo_still_matches(conn):
    _import(conn, "qrcode.html")
    exact = [(r.purchased_at, r.unit_price) for r in search_prices(conn, "picanha")]
    typo = [(r.purchased_at, r.unit_price) for r in search_prices(conn, "pcanha")]
    assert typo == exact


def test_unrelated_term_returns_empty(conn):
    _import(conn, "qrcode.html")
    assert search_prices(conn, "hortifruti") == []


def test_closest_names_returns_near_misses_that_search_would_not_match(conn):
    _import(conn, "qrcode.html")
    assert search_prices(conn, "pikana") == []
    names = closest_names(conn, "pikana")
    assert names and names[0][0] == "PICANHA BOV FAT kg PROMO"
    assert all(score < 100 for _, score in names)
    assert names == sorted(names, key=lambda item: -item[1])
    assert len(closest_names(conn, "pikana", limit=1)) == 1


def test_closest_names_excludes_names_search_already_matches(conn):
    _import(conn, "qrcode.html")
    assert search_prices(conn, "pcanha")
    assert all(name != "PICANHA BOV FAT kg PROMO" for name, _ in closest_names(conn, "pcanha"))


def test_closest_names_empty_when_nothing_close(conn):
    _import(conn, "qrcode.html")
    assert closest_names(conn, "xyzabc") == []
    assert closest_names(conn, "hortifruti") == []


def test_never_mixes_units_in_highlight(conn):
    a = _product(conn, "AGUA MINERAL 500ML", "1")
    b = _product(conn, "AGUA MINERAL GALAO", "2")
    _price(conn, a, "UN", 5.0, "2026-01-01T00:00:00", "k1")
    _price(conn, a, "UN", 10.0, "2026-01-02T00:00:00", "k2")
    _price(conn, b, "KG", 7.0, "2026-01-03T00:00:00", "k3")
    rows = search_prices(conn, "agua")
    assert [row.unit for row in rows] == ["KG", "UN", "UN"]
    by_price = {row.unit_price: row.highlight for row in rows}
    assert by_price == {7.0: None, 10.0: "highest", 5.0: "lowest"}


def test_products_from_different_stores_are_not_merged(conn):
    _import(conn, "qrcode.html")
    _import(conn, "qrcode-3.html")
    rows = search_prices(conn, "tomate")
    italiano_ids = {row.product_id for row in rows if "TOMATE ITALIANO" in row.canonical_name}
    assert len(italiano_ids) == 2
    assert len({row.product_id for row in rows}) == 3  # + TOMATE TREBESCHI 250G DUO, also a real match


def test_tag_filters_and_text_does_not(conn):
    _import(conn, "qrcode.html")
    cebola, tomate = _id_of(conn, "CEBOLA"), _id_of(conn, "TOMATE")
    add_tag(conn, cebola, "hortifruti")
    add_tag(conn, tomate, "hortifruti")
    assert {row.product_id for row in search_prices(conn, tag="hortifruti")} == {cebola, tomate}
    assert search_prices(conn, term="hortifruti") == []


def test_term_and_tag_intersect(conn):
    _import(conn, "qrcode.html")
    cebola, tomate = _id_of(conn, "CEBOLA"), _id_of(conn, "TOMATE")
    add_tag(conn, cebola, "hortifruti")
    add_tag(conn, tomate, "hortifruti")
    assert {row.product_id for row in search_prices(conn, term="tomate", tag="hortifruti")} == {tomate}
    assert search_prices(conn, term="tomate", tag="limpeza") == []


def test_limit_keeps_newest_but_always_includes_extremes(conn):
    product = _product(conn, "ARROZ 5KG", "1")
    for day, price in enumerate([1.0, 5.0, 6.0, 9.0, 7.0], start=1):
        _price(conn, product, "UN", price, f"2026-01-0{day}T00:00:00", f"k{day}")
    rows = search_prices(conn, "arroz", limit=2)
    assert [row.purchased_at[:10] for row in rows] == ["2026-01-05", "2026-01-04", "2026-01-01"]
    assert [row.highlight for row in rows] == [None, "highest", "lowest"]


def test_requires_term_or_tag(conn):
    with pytest.raises(ValueError, match="term or tag"):
        search_prices(conn)


def test_limit_must_be_positive(conn):
    with pytest.raises(ValueError, match="limit"):
        search_prices(conn, "x", limit=0)


def test_accent_and_case_insensitive(conn):
    product = _product(conn, "PÃO FRANCÊS", "1")
    _price(conn, product, "UN", 1.5, "2026-01-01T00:00:00", "k1")
    assert [row.product_id for row in search_prices(conn, "pao frances")] == [product]


def test_no_prices_for_matched_product_returns_empty(conn):
    _product(conn, "FEIJAO PRETO 1KG", "1")
    assert search_prices(conn, "feijao") == []


def test_records_for_products_highlights_per_unit_and_trims_like_search_prices(conn):
    _import(conn, "qrcode.html")
    ids = {row.product_id for row in search_prices(conn, "picanha")}
    assert records_for_products(conn, sorted(ids), 20) == search_prices(conn, "picanha")


def test_records_for_products_rejects_limit_below_one(conn):
    with pytest.raises(ValueError, match="limit"):
        records_for_products(conn, [1], 0)


def test_catalog_for_matching_returns_id_name_tags_sorted_by_id(conn):
    _import(conn, "qrcode.html")
    cebola = _id_of(conn, "CEBOLA")
    add_tag(conn, cebola, "hortifruti")
    catalog = catalog_for_matching(conn)
    assert [row[0] for row in catalog] == sorted(row[0] for row in catalog)
    assert next(row for row in catalog if row[0] == cebola)[1:] == ("CEBOLA UNIAO kg", ("hortifruti",))
