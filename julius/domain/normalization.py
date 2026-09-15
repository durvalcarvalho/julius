from __future__ import annotations

from .models import ContentUnit, SaleUnit

# Raw sale-unit codes observed in real DF receipts. Unknown codes fail loudly on purpose:
# extend this by one line when a new one shows up (see CLAUDE.md, "Contrato do parser").
UNIT_MAP: dict[str, SaleUnit] = {
    "UN1": "UN",
    "UN": "UN",
    "PC": "UN",
    "GF": "UN",
    "KG1": "KG",
    "KG": "KG",
}

_CONTENT_UNITS: dict[str, tuple[ContentUnit, int]] = {
    "L": ("L", 1),
    "ML": ("L", 1000),
    "KG": ("KG", 1),
    "G": ("KG", 1000),
    "UN": ("UN", 1),
}


class UnknownUnitError(ValueError):
    def __init__(self, raw_unit: str, description: str = "", source: str = "") -> None:
        self.raw_unit = raw_unit
        where = f" in {description!r}" if description else ""
        where += f" ({source})" if source else ""
        super().__init__(
            f"unknown sale unit {raw_unit!r}{where} — add it to UNIT_MAP in julius/domain/normalization.py"
        )


def normalize_sale_unit(raw_unit: str, *, description: str = "", source: str = "") -> SaleUnit:
    try:
        return UNIT_MAP[raw_unit.strip().upper()]
    except KeyError:
        raise UnknownUnitError(raw_unit, description, source) from None


def normalize_content(quantity: float, raw_unit: str) -> tuple[float, ContentUnit]:
    if quantity <= 0:
        raise ValueError(f"content quantity must be positive, got {quantity}")
    try:
        unit, divisor = _CONTENT_UNITS[raw_unit.strip().upper()]
    except KeyError:
        raise ValueError(
            f"unknown content unit {raw_unit!r}; expected one of {', '.join(_CONTENT_UNITS)}"
        ) from None
    return quantity / divisor, unit


def parse_decimal_br(text: str) -> float:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("empty number")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    return float(cleaned)


def digits_only(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())
