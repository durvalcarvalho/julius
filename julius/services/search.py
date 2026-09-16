from __future__ import annotations

import sqlite3
from collections.abc import Sequence
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

Known false positive (v2, different constant/function than the "queijo" one below):
"carne" vs "PAO DE ALHO PRADELLA 400G PICANTE" scores 72 — crosses the cutoff, so `julius
consultar carne` matches garlic bread deterministically and never reaches the AI fallback in
`cli/receipts.py`. "carnes" (65) correctly misses instead; tests use "carnes" for this reason.
"""

NEAR_MISS_CUTOFF = 70
"""Minimum fuzz.ratio (0-100) between the term and a single word of a non-matching name for a
"did you mean" suggestion.

WRatio cannot do this job: a short term against a long name bottoms out at 45-60 for any input
("xyzabc" scores 45 against "CHA LEAO RELAXA...", "leite" 67.5 against "PAO ZINHO ... BAGUETE"),
so a WRatio band below MATCH_SCORE_CUTOFF is all noise. Word-level ratio measured on the 5 real
receipts: "pikana" -> PICANHA 77 and "arros" -> ARR 75 stay in; "frango" -> FGO 67 and
"sabao" -> ARBO 67 stay out. Known false positive: "queijo" -> QUERO 73.
"""


def search_prices(
    conn: sqlite3.Connection,
    term: str | None = None,
    tag: str | None = None,
    limit: int = 20,
) -> list[PriceRecord]:
    if term is None and tag is None:
        raise ValueError("term or tag is required")
    return records_for_products(conn, sorted(_candidate_ids(conn, term, tag)), limit)


def records_for_products(conn: sqlite3.Connection, product_ids: Sequence[int], limit: int) -> list[PriceRecord]:
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    records = prices.prices_for_products(conn, product_ids)
    groups: dict[str, list[PriceRecord]] = {}
    for record in records:
        groups.setdefault(record.unit, []).append(record)
    result: list[PriceRecord] = []
    for unit in sorted(groups):
        result.extend(_highlight_and_trim(groups[unit], limit))
    return result


def catalog_for_matching(conn: sqlite3.Connection) -> list[tuple[int, str, tuple[str, ...]]]:
    rows = [(product.id, product.canonical_name, product.tags) for product in products.list_products(conn)]
    return sorted(rows, key=lambda row: row[0])


def closest_names(conn: sqlite3.Connection, term: str, limit: int = 3) -> list[tuple[str, int]]:
    """Names that search_prices would NOT match but have one word close to the term, best first."""
    normalized_term = normalize_text(term)
    matched = _matching_ids(conn, term)
    scores: dict[str, int] = {}
    for product_id, name in products.product_names(conn):
        if product_id in matched:
            continue
        score = max((fuzz.ratio(normalized_term, word) for word in normalize_text(name).split()), default=0)
        if score >= NEAR_MISS_CUTOFF:
            scores[name] = max(int(score), scores.get(name, 0))
    return sorted(scores.items(), key=lambda item: -item[1])[:limit]


def _matching_ids(conn: sqlite3.Connection, term: str) -> set[int]:
    names = {product_id: normalize_text(name) for product_id, name in products.product_names(conn)}
    matches = process.extract(
        normalize_text(term), names, scorer=fuzz.WRatio, score_cutoff=MATCH_SCORE_CUTOFF, limit=None
    )
    return {product_id for _, _, product_id in matches}


def _candidate_ids(conn: sqlite3.Connection, term: str | None, tag: str | None) -> set[int]:
    ids: set[int] | None = None
    if term is not None:
        ids = _matching_ids(conn, term)
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
