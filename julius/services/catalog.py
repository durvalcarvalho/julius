from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence

from rapidfuzz import fuzz

from julius.config import Config
from julius.domain.models import Product, ProductComparison, Store, StoreNaming
from julius.domain.normalization import compose_nickname, is_unnamed, normalize_content, normalize_text, store_place
from julius.infra import cnpj_client
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


def unnamed_stores(conn: sqlite3.Connection) -> list[Store]:
    """Stores the user has not named yet — candidates for naming.

    `nickname == legal_name` is the predicate the rename hint already uses. A nickname this code
    composed from the place alone counts as unnamed too, because it is provisional: without it, a
    registry that was merely unreachable would cost the trade name permanently, since the store
    would look named from then on. A nickname typed by hand matches neither form and is never a
    candidate (RF2).

    ponytail: a store no source will ever know is looked up again on every pass — one free HTTP
    call per `importar`, and one cheap AI call per `mercados revisar`, which the user runs on
    purpose. No budget is spent by importing. Worth revisiting only if a "we already asked"
    marker ever becomes cheaper than that, which would take a new column.
    """
    return [store for store in stores.list_stores(conn) if is_unnamed(store.nickname, store.legal_name, store.address)]


def name_stores(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient | None,
    *,
    cnpjs: Sequence[str] | None = None,
    fetch_trade_name: Callable[[str], str | None] | None = None,
) -> list[StoreNaming]:
    """Give unnamed stores a nickname a human recognises: trade name plus neighbourhood.

    The two sources are complementary, not redundant, so the order is the measured one: the CNPJ
    registry first (free, covers the local store that nobody outside the bairro knows), and the
    model only for what the registry leaves empty (covers the national chain whose branch never
    declared a trade name). Nothing here is derived on read: the trade name costs a network call,
    and recomputing it per `consultar` would break the frequency rule the AI budget rests on — so
    the composed nickname is stored once, and `mercados renomear` is the undo.
    """
    # Looked up through the module, not bound as a default argument: a default is evaluated once
    # at import time, which would make this impossible to replace and let tests reach the real
    # registry over the network.
    fetch = fetch_trade_name or cnpj_client.fetch_trade_name
    candidates = unnamed_stores(conn)
    if cnpjs is not None:
        wanted = set(cnpjs)
        candidates = [store for store in candidates if store.cnpj in wanted]
    if not candidates:
        return []

    trade_names: dict[str, tuple[str, str]] = {}
    for store in candidates:
        found = _safe_trade_name(fetch, store.cnpj)
        if found:
            trade_names[store.cnpj] = (found, "registry")

    missing = [store for store in candidates if store.cnpj not in trade_names]
    if missing and client is not None:
        asked = suggestions.suggest_trade_names(
            conn, config, client, [(s.cnpj, s.legal_name, s.address) for s in missing]
        )
        for cnpj, trade_name in asked.items():
            trade_names[cnpj] = (trade_name, "ai")

    applied: list[StoreNaming] = []
    for store in candidates:
        trade_name, source = trade_names.get(store.cnpj, (None, "place"))
        place = store_place(store.address)
        nickname = compose_nickname(store.legal_name, trade_name, place)
        if nickname is None or nickname == store.nickname:
            continue
        rename_store(conn, store.cnpj, nickname)
        applied.append(
            StoreNaming(
                cnpj=store.cnpj,
                before=store.nickname,
                after=nickname,
                trade_name=trade_name,
                place=place,
                source=source,  # type: ignore[arg-type]
            )
        )
    return applied


def _safe_trade_name(fetch: Callable[[str], str | None], cnpj: str) -> str | None:
    """The client already swallows its own failures; this also covers an injected one that does not,
    because a naming lookup must never be what breaks an import."""
    try:
        found = fetch(cnpj)
    except Exception:
        return None
    return found.strip() or None if isinstance(found, str) else None
