from __future__ import annotations

import functools
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import ParamSpec

from julius.config import Config
from julius.domain.models import Hint, ImportResult, PriceRecord, Store
from julius.domain.normalization import UnknownUnitError, is_unnamed, suggest_nickname
from julius.parsers import ReceiptParseError
from julius.repositories import products, stores
from julius.services import search

MAX_HINTS = 2
_DETAIL_SEPARATOR = "\t"  # cnpj / suggested nickname, packed so the CLI (not this module) can word the command
PACKAGE_SIZE = re.compile(r"C/\d+|\d+(,\d+)?\s?(ML|L|G|KG)\b", re.IGNORECASE)
_MAX_NAMED_PRODUCTS = 3
_MAX_LISTED_TAGS = 5

P = ParamSpec("P")


def _hint_producer(fn: Callable[P, list[Hint]]) -> Callable[P, list[Hint]]:
    """A hint that fails is a hint that does not appear: never raise, never exceed MAX_HINTS."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> list[Hint]:
        try:
            return fn(*args, **kwargs)[:MAX_HINTS]
        except Exception:
            return []

    return wrapper


@_hint_producer
def after_search(conn: sqlite3.Connection, term: str | None, tag: str | None, records: list[PriceRecord]) -> list[Hint]:
    if records:
        return []
    if not stores.list_stores(conn):
        return [Hint("NO_RECEIPTS_IMPORTED")]
    hints: list[Hint] = []
    tags = products.all_tag_names(conn)
    if tag is not None and tag.strip().lower() not in tags:
        hints.append(Hint("UNKNOWN_TAG", tuple(tags)))
    # With a tag, an empty result may just be an empty intersection of a matching term and a valid tag.
    if term is not None and not (tag and search.search_prices(conn, term=term)):
        near = search.closest_names(conn, term)
        if near:
            hints.append(Hint("NO_MATCH_DID_YOU_MEAN", tuple(name for name, _ in near)))
        else:
            hints.append(Hint("NO_MATCH_TRY_TAGS", tuple(tags[:_MAX_LISTED_TAGS])))
    return hints


@_hint_producer
def after_import(conn: sqlite3.Connection, result: ImportResult, *, reviewed: bool = False) -> list[Hint]:
    hints: list[Hint] = []
    if not reviewed:
        pending = [
            product
            for product in map(functools.partial(products.get_product, conn), result.new_product_ids)
            if product and not product.tags
        ]
        if pending:
            hints.append(Hint("PRODUCTS_PENDING_REVIEW", (str(len(pending)),)))
    same_chain = _same_chain_hint(conn)
    if same_chain:
        hints.append(same_chain)
    unnamed = [store for store in stores.list_stores(conn) if is_unnamed(store.nickname, store.legal_name, store.address)]
    if unnamed:
        hints.append(Hint("FIRST_IMPORT_NAME_STORES", tuple(_naming_detail(store) for store in unnamed)))
    if not reviewed:
        sized = [
            product
            for product in map(functools.partial(products.get_product, conn), result.new_product_ids)
            if product and product.content_quantity is None and PACKAGE_SIZE.search(product.canonical_name)
        ]
        if sized:
            details = [f"{product.id} · {product.canonical_name}" for product in sized[:_MAX_NAMED_PRODUCTS]]
            if len(sized) > _MAX_NAMED_PRODUCTS:
                details.append(f"+{len(sized) - _MAX_NAMED_PRODUCTS}")
            hints.append(Hint("PACKAGE_SIZE_IN_DESCRIPTION", tuple(details)))
    return hints


def _naming_detail(store: Store) -> str:
    """cnpj + suggested nickname, packed for `cli/_hints.py` to word as a ready `renomear` command --
    this module diagnoses, the CLI owns command syntax (same split as `_review.py::_undo_command`)."""
    return f"{store.cnpj}{_DETAIL_SEPARATOR}{suggest_nickname(store.legal_name, store.address)}"


def _same_chain_hint(conn: sqlite3.Connection) -> Hint | None:
    groups: dict[str, list[Store]] = {}
    for store in stores.list_stores(conn):
        groups.setdefault(store.cnpj[:8], []).append(store)
    for radical in sorted(groups):
        group = groups[radical]
        pending = [store for store in group if is_unnamed(store.nickname, store.legal_name, store.address)]
        if len(group) >= 2 and pending:
            ordered = sorted(pending, key=lambda store: store.cnpj)
            return Hint("SAME_CHAIN_BRANCHES", tuple(_naming_detail(store) for store in ordered))
    return None


@_hint_producer
def after_ai_fallback(records: list[PriceRecord]) -> list[Hint]:
    if not records:
        return []
    seen: list[tuple[int, str]] = []
    for record in records:
        pair = (record.product_id, record.canonical_name)
        if pair not in seen:
            seen.append(pair)
    details = [f"{product_id} · {name}" for product_id, name in seen[:_MAX_NAMED_PRODUCTS]]
    if len(seen) > _MAX_NAMED_PRODUCTS:
        details.append(f"+{len(seen) - _MAX_NAMED_PRODUCTS}")
    return [Hint("FOUND_VIA_AI", tuple(details))]


@_hint_producer
def for_import_error(error: Exception, path: Path) -> list[Hint]:
    if isinstance(error, FileNotFoundError):
        return [Hint("IMPORT_FILE_NOT_FOUND", (str(path),))]
    if isinstance(error, UnknownUnitError):
        return [Hint("IMPORT_UNKNOWN_UNIT", (error.raw_unit,))]
    # UnicodeDecodeError: a PDF or other binary saved next to the receipts (real case in the input folder).
    if isinstance(error, (ReceiptParseError, UnicodeDecodeError)):
        return [Hint("IMPORT_NOT_A_RECEIPT", (path.name,))]
    return []


@_hint_producer
def for_compare(config: Config) -> list[Hint]:
    return [] if config.ai_configured else [Hint("AI_NOT_CONFIGURED")]
