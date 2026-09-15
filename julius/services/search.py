from __future__ import annotations

import sqlite3
from dataclasses import replace

from rapidfuzz import fuzz, process

from julius.domain.models import PriceRecord
from julius.domain.normalization import normalize_text
from julius.repositories import prices, products

MATCH_SCORE_CUTOFF = 70
"""Minimum WRatio (0-100) for a product name to count as a match.

Measured on real names: "PCANHA" vs "PICANHA BOV FAT KG PROMO" scores 75.00000000000001, so 75
only passed by floating-point luck; unrelated words ("HORTIFRUTI", "XYZABC") score 27-38.
70 keeps one-letter typos in with margin and unrelated words out.
"""


def search_prices(
    conn: sqlite3.Connection,
    term: str | None = None,
    tag: str | None = None,
    limit: int = 20,
) -> list[PriceRecord]:
    if term is None and tag is None:
        raise ValueError("term or tag is required")
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    records = prices.prices_for_products(conn, sorted(_candidate_ids(conn, term, tag)))
    groups: dict[str, list[PriceRecord]] = {}
    for record in records:
        groups.setdefault(record.unit, []).append(record)
    result: list[PriceRecord] = []
    for unit in sorted(groups):
        result.extend(_highlight_and_trim(groups[unit], limit))
    return result


def _candidate_ids(conn: sqlite3.Connection, term: str | None, tag: str | None) -> set[int]:
    ids: set[int] | None = None
    if term is not None:
        names = {product_id: normalize_text(name) for product_id, name in products.product_names(conn)}
        matches = process.extract(
            normalize_text(term), names, scorer=fuzz.WRatio, score_cutoff=MATCH_SCORE_CUTOFF, limit=None
        )
        ids = {product_id for _, _, product_id in matches}
    if tag is not None:
        tagged = set(products.product_ids_with_tag(conn, tag.strip().lower()))
        ids = tagged if ids is None else ids & tagged
    return ids or set()


def _highlight_and_trim(group: list[PriceRecord], limit: int) -> list[PriceRecord]:
    group = sorted(group, key=lambda record: record.purchased_at, reverse=True)
    lowest = min(record.unit_price for record in group)
    highest = max(record.unit_price for record in group)
    kept = group[:limit] + [record for record in group[limit:] if record.unit_price in (lowest, highest)]
    if lowest == highest:
        return kept
    return [
        replace(
            record,
            highlight="lowest" if record.unit_price == lowest else "highest" if record.unit_price == highest else None,
        )
        for record in kept
    ]
