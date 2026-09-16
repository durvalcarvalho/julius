from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SaleUnit = Literal["UN", "KG"]
ContentUnit = Literal["L", "KG", "UN"]
Highlight = Literal["lowest", "highest"]
HintKind = Literal[
    "NO_RECEIPTS_IMPORTED",
    "NO_MATCH_DID_YOU_MEAN",
    "NO_MATCH_TRY_TAGS",
    "UNKNOWN_TAG",
    "FIRST_IMPORT_NAME_STORES",
    "PACKAGE_SIZE_IN_DESCRIPTION",
    "IMPORT_FILE_NOT_FOUND",
    "IMPORT_NOT_A_RECEIPT",
    "IMPORT_UNKNOWN_UNIT",
    "AI_NOT_CONFIGURED",
]


@dataclass(frozen=True)
class Store:
    cnpj: str
    legal_name: str
    nickname: str
    address: str | None = None


@dataclass(frozen=True)
class Product:
    id: int
    canonical_name: str
    content_quantity: float | None = None
    content_unit: ContentUnit | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReceiptItem:
    index: int  # 1-based position in the receipt; part of the price primary key
    product_code: str
    description: str
    quantity: float
    unit: SaleUnit
    unit_price: float
    total_price: float


@dataclass(frozen=True)
class Receipt:
    access_key: str
    issued_at: str  # ISO 8601, taken from "Emissão" — never from the page's consultation timestamp
    store_cnpj: str
    store_legal_name: str
    items: tuple[ReceiptItem, ...]
    store_address: str | None = None


@dataclass(frozen=True)
class PriceRecord:
    product_id: int
    canonical_name: str
    store_nickname: str
    unit: SaleUnit
    unit_price: float
    purchased_at: str
    price_per_content: float | None = None
    content_unit: ContentUnit | None = None
    highlight: Highlight | None = None


@dataclass(frozen=True)
class ImportResult:
    new_items: int
    existing_items: int
    new_product_ids: tuple[int, ...] = ()  # products first seen in this import, in receipt order


@dataclass(frozen=True)
class Hint:
    """A usage hint as data; the CLI owns the wording (see julius/cli/_hints.py)."""

    kind: HintKind
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class MergeSuggestion:
    same_product: bool
    confidence: float
    rationale: str


@dataclass(frozen=True)
class ContentSuggestion:
    quantity: float
    unit: ContentUnit
    confidence: float


@dataclass(frozen=True)
class ProductComparison:
    text_similarity: float
    ai_suggestion: MergeSuggestion | None = None
