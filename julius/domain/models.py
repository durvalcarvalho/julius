from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SaleUnit = Literal["UN", "KG"]
ContentUnit = Literal["L", "KG", "UN"]
Highlight = Literal["lowest", "highest"]
Basis = Literal["unit_price", "price_per_content"]  # see julius/domain/comparison_basis.py
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
    "SAME_CHAIN_BRANCHES",
    "PRODUCTS_PENDING_REVIEW",
    "FOUND_VIA_AI",
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
    kind: str | None = None  # comparison group; NULL until assigned


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
    store_address: str | None = None
    kind: str | None = None  # of the product this row belongs to
    access_key: str = ""  # of the receipt this row came from; lets a caller tell new rows from history


@dataclass(frozen=True)
class ImportResult:
    new_items: int
    existing_items: int
    new_product_ids: tuple[int, ...] = ()  # products first seen in this import, in receipt order
    access_key: str = ""  # of the receipt, so the caller can archive the file without reparsing
    purchased_at: str = ""


@dataclass(frozen=True)
class SearchOutcome:
    """What `consultar` did with free-text words: which word (if any) resolved to a tag
    automatically, and whether an empty tag-filtered result was retried as a plain term search."""

    records: tuple[PriceRecord, ...]
    term: str | None
    tag: str | None
    detected_tag: str | None = None  # the candidate found, even if discarded by the retry


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


PackagingForm = Literal["unit", "pack", "weight", "volume", "unknown"]


@dataclass(frozen=True)
class PackagingHint:
    """How Brazilian retail usually sells this. Never written anywhere: it only feeds the options
    of a question a human answers (ticket 135)."""

    form: PackagingForm
    candidates: tuple[ContentSuggestion, ...]  # best first, at most 3; empty when the model had none


@dataclass(frozen=True)
class ProductComparison:
    text_similarity: float
    ai_suggestion: MergeSuggestion | None = None


@dataclass(frozen=True)
class ProductEnrichment:
    readable_name: str
    tags: tuple[str, ...]  # best first; len > 1 means the model was unsure
    content: ContentSuggestion | None
    kind: str | None  # comparison group proposed by the model


@dataclass(frozen=True)
class ProductProposal:
    product_id: int
    current_name: str
    receipt_description: str  # what the coupon said; "" when the product has no price yet
    readable_name: str | None  # None => keep current (manually renamed before, or model kept it)
    tags: tuple[str, ...]
    tag: str | None  # first candidate that already exists in the vocabulary; None => nothing to apply
    content: ContentSuggestion | None
    kind: str | None  # None => nothing to apply
    sold_by_unit: bool  # whether content is worth asking about at all


@dataclass(frozen=True)
class StorePrice:
    store_nickname: str
    price: float  # on the comparison basis
    purchased_at: str


@dataclass(frozen=True)
class KindComparison:
    kind: str
    unit: SaleUnit
    basis: Basis
    content_unit: ContentUnit | None  # set only when basis is price_per_content
    entries: tuple[StorePrice, ...]  # one per store, cheapest first


@dataclass(frozen=True)
class StoreComparison:
    comparisons: tuple[KindComparison, ...]
    first_purchase: str
    last_purchase: str


@dataclass(frozen=True)
class PriceExtreme:
    product_name: str
    store_nickname: str
    unit: SaleUnit
    price: float  # on the comparison basis
    highlight: Highlight
    basis: Basis
    content_unit: ContentUnit | None
    previous_price: float
    previous_store: str
    previous_at: str
    scope: str  # the kind, or the product's name when it has none


@dataclass(frozen=True)
class AppliedAction:
    """One field the curation actually changed. Text on purpose, so the log stays readable and
    stable; the CLI is what turns this into an undo command, since it owns the command syntax."""

    product_id: int
    field: Literal["name", "tag", "content", "kind"]
    before: str | None
    after: str | None


@dataclass(frozen=True)
class DuplicateCandidate:
    product_a: Product
    product_b: Product
    text_similarity: float
    ai: MergeSuggestion | None
