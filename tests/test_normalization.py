import pytest

from julius.domain.normalization import (
    UnknownUnitError,
    digits_only,
    normalize_content,
    normalize_sale_unit,
    parse_decimal_br,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("UN1", "UN"),
        ("UN", "UN"),
        ("Un", "UN"),
        ("PC", "UN"),
        ("Gf", "UN"),
        ("KG1", "KG"),
        ("KG", "KG"),
        ("Kg", "KG"),
        ("  kg ", "KG"),
    ],
)
def test_normalize_sale_unit_maps_every_code_seen_in_real_receipts(raw, expected):
    assert normalize_sale_unit(raw) == expected


def test_normalize_sale_unit_unknown_code_fails_loudly_with_context():
    with pytest.raises(UnknownUnitError) as exc_info:
        normalize_sale_unit("LT", description="LEITE INTEGRAL 1L", source="nota.html")
    message = str(exc_info.value)
    assert "'LT'" in message
    assert "LEITE INTEGRAL 1L" in message
    assert "nota.html" in message
    assert exc_info.value.raw_unit == "LT"


def test_normalize_sale_unit_never_guesses_from_prefix():
    with pytest.raises(UnknownUnitError):
        normalize_sale_unit("UND")


@pytest.mark.parametrize(
    ("quantity", "unit", "expected"),
    [
        (500, "G", (0.5, "KG")),
        (1.5, "L", (1.5, "L")),
        (750, "ml", (0.75, "L")),
        (2, "kg", (2.0, "KG")),
        (30, "UN", (30.0, "UN")),
    ],
)
def test_normalize_content_converts_to_base_unit(quantity, unit, expected):
    assert normalize_content(quantity, unit) == expected


@pytest.mark.parametrize("quantity", [0, -1, -0.5])
def test_normalize_content_rejects_non_positive_quantity(quantity):
    with pytest.raises(ValueError, match="positive"):
        normalize_content(quantity, "KG")


def test_normalize_content_rejects_unknown_unit():
    with pytest.raises(ValueError, match="unknown content unit"):
        normalize_content(1, "OZ")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("6,99", 6.99),
        ("1.532", 1.532),
        ("1.0000", 1.0),
        ("0.5780", 0.578),
        ("115,90", 115.9),
        ("1.234,56", 1234.56),
        (" 3,69 ", 3.69),
    ],
)
def test_parse_decimal_br_handles_both_separators(text, expected):
    assert parse_decimal_br(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "   ", "abc", "1,2,3"])
def test_parse_decimal_br_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_decimal_br(text)


def test_digits_only_strips_cnpj_and_access_key_formatting():
    assert digits_only("27.289.076/0013-79") == "27289076001379"
    assert (
        digits_only("5326 0927 2890 7600 1379 6520 6000 2038 9519 3076 8277")
        == "53260927289076001379652060002038951930768277"
    )
    assert digits_only("abc") == ""
