import re
from pathlib import Path

import pytest

from julius.domain.normalization import UnknownUnitError
from julius.parsers import ReceiptParseError
from julius.parsers.df import DFReceiptParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"

EXPECTED = {
    "qrcode.html": ("FL 3 COSTA MULTICANAL S A", "27289076001379", 20, "2026-09-12T13:09:16"),
    "qrcode-2.html": ("COMERCIAL DE ALIMENTOS HTP LTDA", "20209736000181", 1, "2026-09-05T16:50:34"),
    "qrcode-3.html": ("DONA DE CASA S/A", "11832478000285", 6, "2026-09-07T18:18:30"),
    "qrcode-4.html": ("DONA DE CASA S/A", "11832478000366", 12, "2026-09-10T10:03:56"),
    "qrcode-5.html": ("SENDAS DISTRIBUIDORA S/A", "06057223052643", 47, "2026-09-04T17:51:40"),
}
SUMMARY_LABELS = ("Valor a pagar", "Qtd. total", "Forma de pagamento", "Tributos")


def _load(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _parse(name: str):
    return DFReceiptParser().parse(_load(name), source=name)


@pytest.mark.parametrize("name", EXPECTED)
def test_item_count_matches_receipt_total(name):
    assert len(_parse(name).items) == EXPECTED[name][2]


@pytest.mark.parametrize("name", EXPECTED)
def test_header_fields(name):
    legal_name, cnpj, _, issued_at = EXPECTED[name]
    receipt = _parse(name)
    assert receipt.store_legal_name == legal_name
    assert receipt.store_cnpj == cnpj
    assert receipt.issued_at == issued_at
    assert len(receipt.access_key) == 44 and receipt.access_key.isdigit()


def test_access_key_values():
    assert _parse("qrcode.html").access_key == "53260927289076001379652060002038951930768277"
    assert _parse("qrcode-5.html").access_key == "53260906057223052643650110001955171111265303"


def test_repeated_code_yields_distinct_items():
    for name, code, times in [("qrcode.html", "14578", 3), ("qrcode-4.html", "29507", 3)]:
        indexes = [item.index for item in _parse(name).items if item.product_code == code]
        assert len(indexes) == times
        assert len(set(indexes)) == times


def test_units_are_normalized_across_all_spellings():
    receipt = _parse("qrcode-5.html")
    assert {item.unit for item in receipt.items} <= {"UN", "KG"}
    by_code = {item.product_code: item for item in receipt.items}
    assert by_code["1057154"].description == "AC MASC F TER ES 1kg"
    assert by_code["1057154"].unit == "UN"
    assert by_code["1057154"].unit_price == 14.85
    assert by_code["8262"].description == "MANGA ROSA kg"
    assert by_code["8262"].unit == "KG"


def test_decimal_separators_do_not_leak_between_fields():
    (item,) = _parse("qrcode-2.html").items
    assert item.quantity == 1.532
    assert item.unit_price == 53.99
    assert item.total_price == 82.71


def test_weighed_item():
    item = next(i for i in _parse("qrcode.html").items if i.description == "LING FGO RESF AURORA kg")
    assert item.quantity == 0.578
    assert item.unit == "KG"
    assert item.total_price == 17.33


@pytest.mark.parametrize("name", EXPECTED)
def test_issued_at_is_not_the_consultation_timestamp(name):
    consultation = re.search(r"Data/Hora da Consulta: \S+ (\d{2}:\d{2}:\d{2})", _load(name)).group(1)
    assert not _parse(name).issued_at.endswith(consultation)


@pytest.mark.parametrize("name", EXPECTED)
def test_summary_blocks_are_not_items(name):
    for item in _parse(name).items:
        assert not any(label in item.description for label in SUMMARY_LABELS)


def test_unknown_unit_raises_with_source():
    html = _load("qrcode-2.html").replace("</strong>KG<strong>", "</strong>LT<strong>")
    with pytest.raises(UnknownUnitError) as exc_info:
        DFReceiptParser().parse(html, source="nota.html")
    assert "'LT'" in str(exc_info.value)
    assert "nota.html" in str(exc_info.value)


def test_missing_header_raises_parse_error():
    html = _load("qrcode-2.html").replace("Chave de acesso:", "")
    with pytest.raises(ReceiptParseError, match="access key"):
        DFReceiptParser().parse(html, source="nota.html")


def test_no_items_raises_parse_error():
    html = re.sub(r"<small>\s*\(Cód:", "<small>(X:", _load("qrcode-2.html"))
    with pytest.raises(ReceiptParseError, match="no items"):
        DFReceiptParser().parse(html)


def test_item_count_mismatch_raises():
    html = _load("qrcode-3.html").replace("<strong>6</strong>", "<strong>7</strong>")
    with pytest.raises(ReceiptParseError, match="declares 7"):
        DFReceiptParser().parse(html)
