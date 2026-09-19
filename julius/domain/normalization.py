from __future__ import annotations

import unicodedata

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


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_accents.upper().split())


def store_place(address: str | None) -> str | None:
    """The neighbourhood from a DF receipt's store address — what tells two branches of one chain
    apart. Counted from the right (`..., BAIRRO, CIDADE, UF`) because a comma inside the street
    name shifts any left-anchored index, and an empty middle segment (`, , `) does not. Measured
    on all 5 real addresses; the city is `BRASILIA` in 5 of 5, which is why it is not used here.
    Segment layout is a DF-template assumption, like the parser it comes from."""
    if not address:
        return None
    parts = [part.strip() for part in address.split(",")]
    if len(parts) < 3:
        return None
    place = parts[-3]
    return place or None


NICKNAME_SEPARATOR = " — "  # the format `SAME_CHAIN_BRANCHES` already tells the user to type


def compose_nickname(legal_name: str, trade_name: str | None, place: str | None) -> str | None:
    """A nickname a human recognises: the trade name when some source knew it, plus the
    neighbourhood that tells two branches of one chain apart.

    None means "leave it alone": with neither a trade name nor a place there is nothing to add,
    and the store keeps its legal name so the rename hint goes on offering it.
    """
    if trade_name is None and place is None:
        return None
    head = trade_name or legal_name
    return head if place is None else f"{head}{NICKNAME_SEPARATOR}{place}"


def suggest_nickname(legal_name: str, address: str | None) -> str:
    """A nickname a human can accept as-is when no trade name is known (registry and AI both
    apply first, for free and for a fee respectively -- this is the last, zero-cost fallback):
    the legal name in Title Case plus the neighbourhood. Deliberately not `compose_nickname`,
    whose `trade_name=None` path returns the legal name verbatim -- `is_unnamed` treats that
    exact string as still unnamed, so pasting this suggestion must produce a different one."""
    place = store_place(address)
    head = legal_name.title()
    return head if place is None else f"{head}{NICKNAME_SEPARATOR}{place}"


def is_unnamed(nickname: str, legal_name: str, address: str | None) -> bool:
    """Whether the user still has not given this store a name of their own.

    A nickname composed from the place alone counts as unnamed: it carries the legal name the
    receipt printed, so it is exactly as unrecognisable as before, and treating it as named would
    both silence the rename hint and make an unreachable registry cost the trade name for good.
    One definition, because the hint and the naming must never disagree about who is pending.
    """
    return nickname == legal_name or nickname == compose_nickname(legal_name, None, store_place(address))
