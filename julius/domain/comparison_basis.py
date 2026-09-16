"""Which price two rows may be compared on.

For items sold by KG, `unit_price` already IS the price per content. For items sold by UN it is
the price of the package, so comparing two different package sizes on it is comparing different
bases — the very thing the project forbids. Measured on the real database: the 500ml bottle at
R$ 1,49 was being marked as the cheapest water when per litre (R$ 2,98/L) it is the dearest.
"""

from __future__ import annotations

from collections.abc import Sequence

from julius.domain.models import Basis, PriceRecord

__all__ = ["Basis", "basis_value", "comparison_basis"]


def comparison_basis(records: Sequence[PriceRecord]) -> tuple[Basis, tuple[int, ...]]:
    """Given records that already share the same sale unit, returns the basis to compare on and
    the indices (into `records`) that may take part in the comparison."""
    if not records:
        return "unit_price", ()
    if records[0].unit == "KG":
        return "unit_price", tuple(range(len(records)))
    if len({record.product_id for record in records}) == 1:
        # Same package over time: a legitimate time series on the package price.
        return "unit_price", tuple(range(len(records)))
    with_content = tuple(i for i, record in enumerate(records) if record.price_per_content is not None)
    content_units = {records[i].content_unit for i in with_content}
    if len(with_content) >= 2 and len(content_units) == 1:
        return "price_per_content", with_content
    # Fewer than two comparable rows: silence is the honest answer.
    return "unit_price", ()


def basis_value(record: PriceRecord, basis: Basis) -> float | None:
    """The record's price on that basis; None when the record has no value for it."""
    return record.unit_price if basis == "unit_price" else record.price_per_content
