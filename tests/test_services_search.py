from pathlib import Path

import pytest

from julius.domain.models import Receipt, ReceiptItem
from julius.parsers.df import DFReceiptParser
from julius.repositories.prices import insert_price
from julius.repositories.products import add_tag, product_names, resolve_product_id, set_content
from julius.repositories.stores import ensure_store
from julius.services.search import (
    catalog_for_matching,
    closest_names,
    detect_tag,
    records_for_products,
    search_free_text,
    search_prices,
)

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


def test_highlight_flips_to_cheapest_per_content(conn):
    small = _product(conn, "AGUA MINERAL 500ML", "1")
    big = _product(conn, "AGUA MINERAL 1,5L", "2")
    set_content(conn, small, 0.5, "L")
    set_content(conn, big, 1.5, "L")
    _price(conn, small, "UN", 1.49, "2026-01-01T00:00:00", "k1")
    _price(conn, big, "UN", 3.69, "2026-01-02T00:00:00", "k2")

    highlight = {row.product_id: row.highlight for row in search_prices(conn, "agua mineral")}

    assert highlight == {big: "lowest", small: "highest"}


def test_highlight_absent_when_content_missing_in_mixed_group(conn):
    small = _product(conn, "AGUA MINERAL 500ML", "1")
    big = _product(conn, "AGUA MINERAL 1,5L", "2")
    _price(conn, small, "UN", 1.49, "2026-01-01T00:00:00", "k1")
    _price(conn, big, "UN", 3.69, "2026-01-02T00:00:00", "k2")

    assert {row.highlight for row in search_prices(conn, "agua mineral")} == {None}


def test_highlight_ignores_non_participating_rows(conn):
    small = _product(conn, "AGUA MINERAL 500ML", "1")
    big = _product(conn, "AGUA MINERAL 1,5L", "2")
    unknown = _product(conn, "AGUA MINERAL COPO", "3")
    set_content(conn, small, 0.5, "L")
    set_content(conn, big, 1.5, "L")
    _price(conn, small, "UN", 1.49, "2026-01-01T00:00:00", "k1")
    _price(conn, big, "UN", 3.69, "2026-01-02T00:00:00", "k2")
    _price(conn, unknown, "UN", 0.99, "2026-01-03T00:00:00", "k3")

    highlight = {row.product_id: row.highlight for row in search_prices(conn, "agua mineral")}

    assert highlight == {big: "lowest", small: "highest", unknown: None}


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


def test_detect_tag_matches_single_word_with_typo(conn):
    assert detect_tag(conn, ["leite", "laticinio"]) == ("leite", "laticinios")


def test_detect_tag_matches_whole_query_as_pure_tag(conn):
    assert detect_tag(conn, ["hortifruti"]) == (None, "hortifruti")


def test_detect_tag_no_match_returns_joined_term(conn):
    assert detect_tag(conn, ["frango", "assado"]) == ("frango assado", None)


def test_detect_tag_empty_words(conn):
    assert detect_tag(conn, []) == (None, None)


def test_detect_tag_ignores_words_below_cutoff(conn):
    assert detect_tag(conn, ["queijo"]) == ("queijo", None)


def test_search_free_text_explicit_tag_skips_detection(conn):
    _import(conn, "qrcode.html")
    picanha = _id_of(conn, "PICANHA")
    add_tag(conn, picanha, "carnes")
    outcome = search_free_text(conn, ["picanha"], tag="carnes")
    assert outcome.records == tuple(search_prices(conn, term="picanha", tag="carnes"))
    assert outcome.tag == "carnes"
    assert outcome.detected_tag is None


def test_search_free_text_detects_tag_and_intersects(conn):
    leite = _product(conn, "LEITE INTEGRAL 1L", "1")
    condensado = _product(conn, "LEITE CONDENSADO", "2")
    add_tag(conn, leite, "laticinios")
    _price(conn, leite, "UN", 5.0, "2026-01-01T00:00:00", "k1")
    _price(conn, condensado, "UN", 6.0, "2026-01-02T00:00:00", "k2")
    outcome = search_free_text(conn, ["leite", "laticinios"])
    assert {row.product_id for row in outcome.records} == {leite}
    assert outcome.term == "leite"
    assert outcome.tag == "laticinios"
    assert outcome.detected_tag == "laticinios"


def test_search_free_text_empty_intersection_retries_as_pure_term(conn):
    suco = _product(conn, "BEBIDAS SUCO INTEGRAL", "1")
    _price(conn, suco, "UN", 4.0, "2026-01-01T00:00:00", "k1")
    outcome = search_free_text(conn, ["bebidas", "suco"])
    assert outcome.records == tuple(search_prices(conn, term="bebidas suco", tag=None))
    assert {row.product_id for row in outcome.records} == {suco}
    assert outcome.tag is None
    assert outcome.detected_tag == "bebidas"


def test_search_free_text_pure_tag_query(conn):
    _import(conn, "qrcode.html")
    cebola, tomate = _id_of(conn, "CEBOLA"), _id_of(conn, "TOMATE")
    add_tag(conn, cebola, "hortifruti")
    add_tag(conn, tomate, "hortifruti")
    outcome = search_free_text(conn, ["hortifruti"])
    assert outcome.term is None
    assert {row.product_id for row in outcome.records} == {cebola, tomate}


def test_search_free_text_no_tag_detected_behaves_like_plain_term(conn):
    frango = _product(conn, "FRANGO ASSADO", "1")
    _price(conn, frango, "UN", 12.0, "2026-01-01T00:00:00", "k1")
    outcome = search_free_text(conn, ["frango", "assado"])
    assert outcome.records == tuple(search_prices(conn, term="frango assado", tag=None))
    assert outcome.tag is None
    assert outcome.detected_tag is None


def test_word_in_a_long_name_matches_and_a_lookalike_substring_does_not(conn):
    """Regression: fuzz.WRatio penalized a short term against a long name, so "pao" scored 60
    against a real bread (dropped) and 72 against "...UNIAO" (kept) — the ranking was inverted."""
    bread = _product(conn, "PAO DE FORMA BAUDUCCO TRADICIONAL 390G", "1")
    fruit = _product(conn, "LARANJA PERA UNIAO kg", "2")
    _price(conn, bread, "UN", 7.49, "2026-01-01T00:00:00", "k1")
    _price(conn, fruit, "KG", 2.49, "2026-01-02T00:00:00", "k2")

    assert [row.product_id for row in search_prices(conn, "pao")] == [bread]


def test_abbreviated_term_matches_by_prefix(conn):
    product = _product(conn, "REFRIGERANTE PEPSI PET 2L", "1")
    _price(conn, product, "UN", 6.99, "2026-01-01T00:00:00", "k1")

    assert [row.product_id for row in search_prices(conn, "refri")] == [product]


def test_every_word_of_a_multi_word_term_must_match(conn):
    alho = _product(conn, "PAO DE ALHO PRADELLA 400G PICANTE", "1")
    queijo = _product(conn, "PAO DE QUEIJO BENI TRADICIONAL 800G", "2")
    _price(conn, alho, "UN", 13.99, "2026-01-01T00:00:00", "k1")
    _price(conn, queijo, "UN", 15.99, "2026-01-02T00:00:00", "k2")

    assert [row.product_id for row in search_prices(conn, "pao de alho")] == [alho]
