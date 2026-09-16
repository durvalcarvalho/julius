from pathlib import Path

import pytest

from julius import config
from julius.domain.models import Hint, ImportResult, PriceRecord
from julius.domain.normalization import UnknownUnitError
from julius.parsers import ReceiptParseError
from julius.parsers.df import DFReceiptParser
from julius.repositories import products, stores
from julius.services import guidance
from julius.services.importing import import_receipt
from julius.services.search import search_prices

FIXTURES = Path(__file__).parent / "fixtures"
PARSER = DFReceiptParser()
SEEDED_TAGS = sorted(
    [
        "hortifruti", "carnes", "frios", "laticinios", "padaria", "mercearia",
        "bebidas", "limpeza", "higiene", "congelados", "temperos", "doces", "utilidades",
    ]
)  # migration 0002


def _import(conn, name: str) -> ImportResult:
    return import_receipt(conn, FIXTURES / name, PARSER)


def _kinds(hints: list[Hint]) -> list[str]:
    return [hint.kind for hint in hints]


def _search_hints(conn, term=None, tag=None) -> list[Hint]:
    return guidance.after_search(conn, term, tag, search_prices(conn, term=term, tag=tag))


def test_after_search_returns_nothing_when_there_are_results(conn):
    _import(conn, "qrcode.html")
    assert _search_hints(conn, "picanha") == []


def test_after_search_empty_db_says_no_receipts(conn):
    assert _search_hints(conn, "banana") == [Hint("NO_RECEIPTS_IMPORTED")]
    assert _search_hints(conn, "banana", tag="inexistente") == [Hint("NO_RECEIPTS_IMPORTED")]


def test_after_search_did_you_mean_lists_near_misses(conn):
    _import(conn, "qrcode.html")
    (hint,) = _search_hints(conn, "pikana")
    assert hint.kind == "NO_MATCH_DID_YOU_MEAN"
    assert "PICANHA BOV FAT kg PROMO" in hint.details
    assert len(hint.details) <= 3


def test_after_search_suggests_tags_when_nothing_is_close(conn):
    _import(conn, "qrcode-3.html")
    products.add_tag(conn, 1, "hortifruti")
    (hint,) = _search_hints(conn, "carne")
    assert hint == Hint("NO_MATCH_TRY_TAGS", tuple(SEEDED_TAGS[:5]))


def test_after_search_unknown_tag_lists_existing_tags(conn):
    _import(conn, "qrcode.html")
    products.add_tag(conn, 1, "bebidas")
    assert _search_hints(conn, tag="carne") == [Hint("UNKNOWN_TAG", tuple(SEEDED_TAGS))]
    # Unknown tag plus a term that matches: the tag is the only problem worth reporting.
    assert _kinds(_search_hints(conn, "picanha", tag="carne")) == ["UNKNOWN_TAG"]
    # Known tag plus a matching term with an empty intersection: nothing wrong to diagnose.
    assert _search_hints(conn, "picanha", tag="bebidas") == []


def test_after_import_flags_stores_without_nickname_then_stops_after_rename(conn):
    result = _import(conn, "qrcode.html")
    assert Hint("FIRST_IMPORT_NAME_STORES", ("1",)) in guidance.after_import(conn, result)
    stores.rename_store(conn, "27289076001379", "FL 3 Costa")
    assert "FIRST_IMPORT_NAME_STORES" not in _kinds(guidance.after_import(conn, result))


def test_after_import_flags_package_size_only_for_new_products_without_content(conn):
    result = _import(conn, "qrcode-5.html")
    stores.rename_store(conn, next(iter(stores.list_stores(conn))).cnpj, "Assaí")
    hints = guidance.after_import(conn, result)
    assert [h.kind for h in hints] == ["PRODUCTS_PENDING_REVIEW", "PACKAGE_SIZE_IN_DESCRIPTION"]
    hint = hints[1]
    assert len(hint.details) == 4 and hint.details[-1] == "+24"
    assert all(" · " in detail for detail in hint.details[:3])

    first_id = int(hint.details[0].split(" · ")[0])
    products.set_content(conn, first_id, 1.0, "KG")
    again = next(h for h in guidance.after_import(conn, result) if h.kind == "PACKAGE_SIZE_IN_DESCRIPTION")
    assert again.details[-1] == "+23"
    assert not again.details[0].startswith(f"{first_id} ·")

    assert guidance.after_import(conn, _import(conn, "qrcode-5.html")) == []


def test_after_import_names_every_sized_product_when_three_or_fewer(conn):
    result = _import(conn, "qrcode-3.html")
    stores.rename_store(conn, "11832478000285", "Dona de Casa")
    hints = guidance.after_import(conn, result)
    assert [h.kind for h in hints] == ["PRODUCTS_PENDING_REVIEW", "PACKAGE_SIZE_IN_DESCRIPTION"]
    hint = hints[1]
    assert len(hint.details) == 2
    assert not hint.details[-1].startswith("+")


@pytest.mark.parametrize(
    ("error", "kind", "detail"),
    [
        (FileNotFoundError(2, "no such file"), "IMPORT_FILE_NOT_FOUND", "/tmp/x/nota.html"),
        (ReceiptParseError("no items found"), "IMPORT_NOT_A_RECEIPT", "nota.html"),
        (UnicodeDecodeError("utf-8", b"\x80", 0, 1, "invalid"), "IMPORT_NOT_A_RECEIPT", "nota.html"),
        (UnknownUnitError("LT", "AGUA", "nota.html"), "IMPORT_UNKNOWN_UNIT", "LT"),
    ],
)
def test_for_import_error_maps_each_exception_type(error, kind, detail):
    assert guidance.for_import_error(error, Path("/tmp/x/nota.html")) == [Hint(kind, (detail,))]


def test_for_import_error_ignores_unknown_exceptions():
    assert guidance.for_import_error(RuntimeError("boom"), Path("x.html")) == []


def test_for_compare_only_when_ai_not_configured():
    assert guidance.for_compare(config.load({})) == [Hint("AI_NOT_CONFIGURED")]
    configured = config.load({"JULIUS_AI_API_KEY": "k", "JULIUS_AI_BASE_URL": "http://x", "JULIUS_AI_MODEL": "m"})
    assert guidance.for_compare(configured) == []


def test_hints_are_capped_at_two(conn):
    result = _import(conn, "qrcode.html")
    assert len(guidance.after_import(conn, result)) == guidance.MAX_HINTS == 2
    assert len(_search_hints(conn, "xyzabc", tag="nada")) == 2


def test_guidance_never_raises_on_closed_connection(conn):
    result = _import(conn, "qrcode.html")
    conn.close()
    assert guidance.after_search(conn, "picanha", None, []) == []
    assert guidance.after_import(conn, result) == []


def test_after_import_pending_review_when_not_reviewed_and_untagged(conn):
    result = _import(conn, "qrcode-2.html")
    assert Hint("PRODUCTS_PENDING_REVIEW", ("1",)) in guidance.after_import(conn, result)
    assert "PRODUCTS_PENDING_REVIEW" not in _kinds(guidance.after_import(conn, result, reviewed=True))
    products.add_tag(conn, result.new_product_ids[0], "mercearia")
    assert "PRODUCTS_PENDING_REVIEW" not in _kinds(guidance.after_import(conn, result))


def test_after_import_same_chain_branches_lists_both_dona_de_casa_with_addresses(conn):
    _import(conn, "qrcode-3.html")
    result = _import(conn, "qrcode-4.html")
    hint = next(h for h in guidance.after_import(conn, result) if h.kind == "SAME_CHAIN_BRANCHES")
    assert any("11832478000285" in detail and "GUARA II" in detail for detail in hint.details)
    assert any("11832478000366" in detail and "CANDANGOLANDIA" in detail for detail in hint.details)


def test_same_chain_hint_stops_after_both_branches_are_renamed(conn):
    _import(conn, "qrcode-3.html")
    result = _import(conn, "qrcode-4.html")
    stores.rename_store(conn, "11832478000285", "Dona de Casa — Guará II")
    stores.rename_store(conn, "11832478000366", "Dona de Casa — Candangolândia")
    assert "SAME_CHAIN_BRANCHES" not in _kinds(guidance.after_import(conn, result))


def test_after_import_order_and_cap_at_two(conn):
    _import(conn, "qrcode-3.html")
    result = _import(conn, "qrcode-4.html")
    hints = guidance.after_import(conn, result)
    assert [h.kind for h in hints] == ["PRODUCTS_PENDING_REVIEW", "SAME_CHAIN_BRANCHES"]
    assert len(hints) == guidance.MAX_HINTS


def test_package_size_hint_suppressed_when_reviewed(conn):
    result = _import(conn, "qrcode-5.html")
    stores.rename_store(conn, next(iter(stores.list_stores(conn))).cnpj, "Assaí")
    assert guidance.after_import(conn, result, reviewed=True) == []


def test_after_ai_fallback_lists_unique_products_max_three_plus_n():
    records = [
        PriceRecord(
            product_id=i,
            canonical_name=f"P{i}",
            store_nickname="S",
            unit="UN",
            unit_price=1.0,
            purchased_at="2026-01-01T00:00:00",
        )
        for i in range(1, 6)
    ]
    (hint,) = guidance.after_ai_fallback(records)
    assert hint.kind == "FOUND_VIA_AI"
    assert hint.details == ("1 · P1", "2 · P2", "3 · P3", "+2")


def test_after_ai_fallback_empty_records_gives_no_hint():
    assert guidance.after_ai_fallback([]) == []
