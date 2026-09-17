from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import replace

from rapidfuzz import fuzz, process

from julius.domain.comparison_basis import basis_value, comparison_basis
from julius.domain.models import PriceRecord, SearchOutcome
from julius.domain.normalization import normalize_text
from julius.repositories import prices, products

MATCH_SCORE_CUTOFF = 80
"""Minimum _name_score (0-100) for a product name to count as a match.

Measured on the real catalog (105 products, AI-written names): every whole-word or prefix hit
scores 100 ("pao" -> the 5 "Pão ..." products, "refri" -> both "Refrigerante ..."), and a
one-edit typo on a short word scores 80 ("arros" -> "Arroz", "pcanha" -> "Picanha" 92). The
false positives that survive at 80 all score exactly 80 and are the price of that typo
tolerance: "pao" -> "Cacau em pó", "vinho" -> "Pão Zinho", "queijo" -> "Requeijão",
"refri" -> "Resfriada". 81 would drop them and every one-edit typo with them.

This replaced fuzz.WRatio, which was measured inverting the ranking: WRatio penalizes a short
term against a long name, so "pao" scored 60 against "Pão de forma Bauducco tradicional 390g"
(dropped) and 72 against "Laranja pera União" (kept, via partial match on "UNIAO"). `consultar
pao` returned 12 fruits and 1 bread; no cutoff value fixes that, only a different scorer.
Two-edit typos stay out, same limitation already accepted by TAG_MATCH_CUTOFF ("pikana" ->
"Picanha" is 77). Known ceiling at the other end: the prefix comparison scores 100 for any name
word starting with the term, so a 1-2 letter term is a prefix listing ("a" and "pa" each match
22 of the 105 products). Wide but never wrong, so no minimum term length is enforced.
"""

NEAR_MISS_CUTOFF = 70
"""Minimum fuzz.ratio (0-100) between the term and a single word of a non-matching name for a
"did you mean" suggestion.

Same word-level comparison as MATCH_SCORE_CUTOFF, minus the prefix bonus, so this is simply the
band just below a match: 70-80. Measured on the 5 real receipts: "pikana" -> PICANHA 77 and
"arros" -> ARR 75 stay in; "frango" -> FGO 67 and "sabao" -> ARBO 67 stay out. Known false
positive: "queijo" -> QUERO 73.
"""

TAG_MATCH_CUTOFF = 75
"""Minimum fuzz.ratio (0-100) for a free-text word to count as a tag (v2.1, natural `consultar`).

Measured against the 13 seeded tags (see migration 0002) with fuzz.ratio on normalize_text: the
71 unique descriptions of the 6 real fixtures plus common grocery words (leite, arroz, queijo,
carne...). Worst real false positive is "PAPRICA" vs "PADARIA" = 71.4 ("TEMP" -> "TEMPEROS" and
"DESC" -> "DOCES" both 66.7). Worst 1-edit typo that must still match is 80.0 ("FIROS"/"FROIS" ->
"FRIOS", "AOCES" -> "DOCES"). 75 keeps margin on both sides. 2-edit typos (e.g. "AACES" vs
"DOCES" = 60) fall outside any reasonable cutoff, same limitation already accepted by
MATCH_SCORE_CUTOFF for product names. No two of the 13 tags score above 55 against each other.
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


def detect_tag(conn: sqlite3.Connection, words: Sequence[str]) -> tuple[str | None, str | None]:
    """Tests each word of `words` against the known tags; the single best-scoring word above
    TAG_MATCH_CUTOFF (if any) is consumed as the tag, the rest re-joined as the term."""
    tags = products.all_tag_names(conn)
    if not tags or not words:
        return " ".join(words) or None, None
    normalized_tags = [normalize_text(t) for t in tags]
    best_index: int | None = None
    best_tag: str | None = None
    best_score = -1.0
    for index, word in enumerate(words):
        match = process.extractOne(normalize_text(word), normalized_tags, scorer=fuzz.ratio, score_cutoff=TAG_MATCH_CUTOFF)
        if match is not None and match[1] > best_score:
            best_index, best_tag, best_score = index, tags[match[2]], match[1]
    if best_index is None:
        return " ".join(words) or None, None
    remaining = [word for i, word in enumerate(words) if i != best_index]
    return " ".join(remaining) or None, best_tag


def search_free_text(
    conn: sqlite3.Connection, words: Sequence[str], tag: str | None = None, limit: int = 20
) -> SearchOutcome:
    """Entry point for `consultar` with free-text words. If `tag` is given explicitly, tag
    detection never runs. Otherwise, a word that matches a known tag is used as a filter
    (intersected with the rest as the term); an empty intersection is retried as a plain term."""
    if tag is not None:
        term = " ".join(words) or None
        return SearchOutcome(tuple(search_prices(conn, term=term, tag=tag, limit=limit)), term, tag)
    remaining_term, detected_tag = detect_tag(conn, words)
    if detected_tag is None:
        records = search_prices(conn, term=remaining_term, tag=None, limit=limit)
        return SearchOutcome(tuple(records), remaining_term, None)
    records = search_prices(conn, term=remaining_term, tag=detected_tag, limit=limit)
    if records:
        return SearchOutcome(tuple(records), remaining_term, detected_tag, detected_tag)
    full_term = " ".join(words) or None
    records = search_prices(conn, term=full_term, tag=None, limit=limit)
    return SearchOutcome(tuple(records), full_term, None, detected_tag)


def records_for_products(conn: sqlite3.Connection, product_ids: Sequence[int], limit: int) -> list[PriceRecord]:
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    records = _collapse(prices.prices_for_products(conn, product_ids))
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


def _name_score(term_words: Sequence[str], name_words: Sequence[str]) -> float:
    """Every word of the term has to find a close word in the name: min over the term's words of
    the best per-word score. The prefix comparison is what keeps an abbreviated term matching
    ("refri" -> "REFRIGERANTE") without letting a substring anywhere in the name count, which is
    how "PAO" used to match "UNIAO". It only works in that direction: an abbreviation in the
    *name* ("LING" for linguiça) still misses, and the durable fix for that is the AI rename."""
    if not term_words or not name_words:
        return 0.0
    return min(
        max(max(fuzz.ratio(word, other), fuzz.ratio(word, other[: len(word)])) for other in name_words)
        for word in term_words
    )


def _matching_ids(conn: sqlite3.Connection, term: str) -> set[int]:
    term_words = normalize_text(term).split()
    return {
        product_id
        for product_id, name in products.product_names(conn)
        if _name_score(term_words, normalize_text(name).split()) >= MATCH_SCORE_CUTOFF
    }


def _candidate_ids(conn: sqlite3.Connection, term: str | None, tag: str | None) -> set[int]:
    ids: set[int] | None = None
    if term is not None:
        ids = _matching_ids(conn, term)
    if tag is not None:
        tagged = set(products.product_ids_with_tag(conn, tag.strip().lower()))
        ids = tagged if ids is None else ids & tagged
    return ids or set()


def _collapse(records: list[PriceRecord]) -> list[PriceRecord]:
    """One row per (group, day, store, price). The same price of the same product on the same day
    at the same store carries no price information twice — it is the item repeated in one receipt.
    Has to happen before the highlight, or the limit is spent on repetition."""
    seen: dict[tuple[int, str, str, float], PriceRecord] = {}
    for record in records:
        # By CNPJ: two branches of one chain share a nickname, and collapsing them would hide a
        # second real purchase behind the first.
        seen.setdefault((record.product_id, record.purchased_at, record.store_cnpj, record.unit_price), record)
    return list(seen.values())


def _highlight_and_trim(group: list[PriceRecord], limit: int) -> list[PriceRecord]:
    group = sorted(group, key=lambda record: record.purchased_at, reverse=True)
    basis, participants = comparison_basis(group)
    if basis == "price_per_content":
        # The question is "which package is worth it", so the useful order is the one the
        # highlight already uses. Rows with no content have no value on this basis and go last.
        group = sorted(group, key=lambda record: (record.price_per_content is None, record.price_per_content or 0.0))
        basis, participants = comparison_basis(group)
    values = {index: value for index in participants if (value := basis_value(group[index], basis)) is not None}
    if len(values) < 2:
        return group[:limit]
    lowest, highest = min(values.values()), max(values.values())
    kept = list(range(min(limit, len(group))))
    kept += [index for index in range(limit, len(group)) if values.get(index) in (lowest, highest)]
    if lowest == highest:
        return [group[index] for index in kept]
    return [
        replace(
            group[index],
            highlight="lowest"
            if values.get(index) == lowest
            else "highest"
            if values.get(index) == highest
            else None,
        )
        for index in kept
    ]
