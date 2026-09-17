from __future__ import annotations

import sqlite3

from rapidfuzz import fuzz

from julius.config import Config
from julius.domain.models import Product, ProductComparison, Store
from julius.domain.normalization import normalize_content, normalize_text
from julius.infra.llm_client import LlmClient
from julius.repositories import prices, products, stores
from julius.services import suggestions


def list_stores(conn: sqlite3.Connection) -> list[Store]:
    return stores.list_stores(conn)


def list_products(conn: sqlite3.Connection) -> list[Product]:
    return products.list_products(conn)


def rename_store(conn: sqlite3.Connection, cnpj: str, nickname: str) -> None:
    with conn:
        stores.rename_store(conn, cnpj, _non_blank(nickname, "nickname"))


def rename_product(conn: sqlite3.Connection, product_id: int, name: str) -> None:
    with conn:
        products.rename_product(conn, product_id, _non_blank(name, "name"))


def merge_products(conn: sqlite3.Connection, source_id: int, target_id: int) -> None:
    if source_id == target_id:
        raise ValueError("source and target must be different products")
    source = _require_product(conn, source_id)
    target = _require_product(conn, target_id)
    with conn:
        products.set_merged_into(conn, source_id, target_id)


def tag_product(conn: sqlite3.Connection, product_id: int, tag: str) -> None:
    with conn:
        products.add_tag(conn, product_id, _non_blank(tag, "tag").lower())


def untag_product(conn: sqlite3.Connection, product_id: int, tag: str) -> None:
    with conn:
        products.remove_tag(conn, product_id, _non_blank(tag, "tag").lower())


def set_product_kind(conn: sqlite3.Connection, product_id: int, kind: str) -> None:
    # The spelling rule lives in products.set_kind so the automatic path cannot bypass it.
    with conn:
        products.set_kind(conn, product_id, _non_blank(kind, "tipo"))


def clear_product_kind(conn: sqlite3.Connection, product_id: int) -> None:
    with conn:
        products.set_kind(conn, product_id, None)


def clear_product_content(conn: sqlite3.Connection, product_id: int) -> None:
    with conn:
        products.clear_content(conn, product_id)


def set_product_content(conn: sqlite3.Connection, product_id: int, quantity: float, raw_unit: str) -> None:
    normalized_quantity, unit = normalize_content(quantity, raw_unit)
    with conn:
        products.set_content(conn, product_id, normalized_quantity, unit)


def compare_products(
    conn: sqlite3.Connection, config: Config, client: LlmClient | None, id_a: int, id_b: int
) -> ProductComparison:
    """An opinion, never an action: merging stays a separate, manual command."""
    if id_a == id_b:
        raise ValueError("cannot compare a product with itself")
    a = _require_product(conn, id_a)
    b = _require_product(conn, id_b)
    similarity = fuzz.token_set_ratio(normalize_text(a.canonical_name), normalize_text(b.canonical_name)) / 100
    suggestion = None
    if client is not None and suggestions.is_available(conn, config):
        suggestion = suggestions.suggest_merges(conn, config, client, [(a.canonical_name, b.canonical_name)])[0]
    return ProductComparison(text_similarity=similarity, ai_suggestion=suggestion)


def _non_blank(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be blank")
    return cleaned


def _require_product(conn: sqlite3.Connection, product_id: int) -> Product:
    product = products.get_product(conn, product_id)
    if product is None:
        raise LookupError(f"product {product_id} not found")
    return product
