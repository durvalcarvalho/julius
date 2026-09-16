from julius.domain.comparison_basis import basis_value, comparison_basis
from julius.domain.models import PriceRecord


def _record(
    product_id: int = 1,
    unit: str = "UN",
    unit_price: float = 1.0,
    content_quantity: float | None = None,
    content_unit: str | None = None,
) -> PriceRecord:
    return PriceRecord(
        product_id=product_id,
        canonical_name=f"P{product_id}",
        store_nickname="S",
        unit=unit,
        unit_price=unit_price,
        purchased_at="2026-01-01T00:00:00",
        price_per_content=None if content_quantity is None else unit_price / content_quantity,
        content_unit=content_unit,
    )


def test_kg_group_always_uses_unit_price():
    group = [_record(1, "KG", 11.89), _record(2, "KG", 14.99), _record(3, "KG", 9.99)]
    assert comparison_basis(group) == ("unit_price", (0, 1, 2))


def test_un_single_product_uses_unit_price():
    group = [_record(1, "UN", 5.0), _record(1, "UN", 10.0)]
    assert comparison_basis(group) == ("unit_price", (0, 1))


def test_un_multi_product_all_with_uniform_content_uses_per_content():
    group = [_record(1, "UN", 1.49, 0.5, "L"), _record(2, "UN", 3.69, 1.5, "L")]
    assert comparison_basis(group) == ("price_per_content", (0, 1))


def test_un_multi_product_partial_content_participates_only_with_content():
    group = [
        _record(1, "UN", 1.49, 0.5, "L"),
        _record(2, "UN", 2.99),
        _record(3, "UN", 3.69, 1.5, "L"),
        _record(4, "UN", 0.99),
    ]
    assert comparison_basis(group) == ("price_per_content", (0, 2))


def test_un_multi_product_mixed_content_units_no_participants():
    group = [_record(1, "UN", 1.49, 0.5, "L"), _record(2, "UN", 3.69, 1.5, "KG")]
    assert comparison_basis(group) == ("unit_price", ())


def test_un_multi_product_single_content_row_no_participants():
    group = [_record(1, "UN", 1.49, 0.5, "L"), _record(2, "UN", 3.69)]
    assert comparison_basis(group) == ("unit_price", ())


def test_empty_group():
    assert comparison_basis([]) == ("unit_price", ())


def test_basis_value():
    with_content = _record(1, "UN", 3.0, 1.5, "L")
    without = _record(2, "UN", 3.0)
    assert basis_value(with_content, "unit_price") == 3.0
    assert basis_value(with_content, "price_per_content") == 2.0
    assert basis_value(without, "price_per_content") is None
