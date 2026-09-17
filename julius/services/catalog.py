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


def get_product(conn: sqlite3.Connection, product_id: int) -> Product | None:
    return products.get_product(conn, product_id)


def rename_store(conn: sqlite3.Connection, cnpj: str, nickname: str) -> None:
    with conn:
        stores.rename_store(conn, cnpj, _non_blank(nickname, "nickname"))


def rename_product(conn: sqlite3.Connection, product_id: int, name: str) -> None:
    with conn:
        products.rename_product(conn, product_id, _non_blank(name, "name"))


def merge_products(conn: sqlite3.Connection, source_id: int, target_id: int) -> None:
    """Records that source belongs to target's group. Nothing is moved and nothing is deleted:
    the group's name, content, kind and tags are composed on read (repositories.products)."""
    if source_id == target_id:
        raise ValueError("origem e destino precisam ser produtos diferentes")
    source = _require_product(conn, source_id)
    _require_product(conn, target_id)
    # A cycle makes the product_group recursion never return, and every command that reads a
    # product stops responding — with no error. This is the only guard against it.
    if products.group_root(conn, target_id) == source_id:
        raise ValueError(
            f"produto {target_id} já faz parte do grupo de {source_id} ({source.canonical_name}); "
            f"desfaça essa fusão antes"
        )
    with conn:
        products.set_merged_into(conn, source_id, target_id)


def unmerge_product(conn: sqlite3.Connection, product_id: int) -> None:
    product = _require_product(conn, product_id)
    if products.group_root(conn, product_id) == product_id:
        raise ValueError(f"produto {product_id} ({product.canonical_name}) não está fundido")
    with conn:
        products.set_merged_into(conn, product_id, None)


def merge_inheritance(conn: sqlite3.Connection, source_id: int, target_id: int) -> tuple[str, str] | None:
    """What the group will gain from this merge, for the CLI to announce. Must be called BEFORE
    merging: afterwards the value is already composed and there is no telling where it came from.
    Returns (field description, source description) or None. Never raises."""
    try:
        source = products.get_product(conn, source_id)
        target = products.get_product(conn, target_id)
        if source is None or target is None:
            return None
        if target.content_quantity is None and source.content_quantity is not None:
            return f"o conteúdo {source.content_quantity:g} {source.content_unit}", f"produto {source_id}"
        if target.kind is None and source.kind is not None:
            return f"o tipo {source.kind}", f"produto {source_id}"
        return None
    except Exception:
        return None


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
