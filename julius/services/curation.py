from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from rapidfuzz import fuzz

from julius.config import Config
from julius.domain.models import DuplicateCandidate, Product, ProductProposal
from julius.domain.normalization import normalize_text
from julius.infra.llm_client import LlmClient
from julius.repositories import products
from julius.services import suggestions

DUPLICATE_CANDIDATE_CUTOFF = 75  # token_set_ratio; measured on the real 70-product catalog (see design doc)
MAX_DUPLICATE_PAIRS = 20  # one merge call per review


def pending_product_ids(conn: sqlite3.Connection) -> list[int]:
    return products.untagged_product_ids(conn)


def propose(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    product_ids: Sequence[int],
) -> list[ProductProposal]:
    found = [(pid, product) for pid in product_ids if (product := products.get_product(conn, pid)) is not None]
    if not found:
        return []
    known = products.all_tag_names(conn)
    enrichment = suggestions.enrich_products(conn, config, client, [product for _, product in found], known)
    proposals: list[ProductProposal] = []
    for product_id, product in found:
        item = enrichment.get(product_id)
        if item is None:
            continue
        readable_name: str | None = item.readable_name.strip()
        same_as_current = readable_name.casefold() == product.canonical_name.strip().casefold()
        if not products.has_raw_name(conn, product_id) or same_as_current:
            readable_name = None
        content = None if product.content_quantity is not None else item.content
        proposals.append(
            ProductProposal(
                product_id=product_id,
                current_name=product.canonical_name,
                readable_name=readable_name,
                tags=item.tags,
                tag_is_known=item.tags[0] in known,
                content=content,
            )
        )
    return proposals


def apply(conn: sqlite3.Connection, proposal: ProductProposal, *, tag: str | None, content: bool) -> None:
    normalized_tag = None
    if tag:
        normalized_tag = tag.strip().lower()
        if not normalized_tag:
            raise ValueError("tag must not be blank")
    with conn:
        if proposal.readable_name:
            products.rename_product(conn, proposal.product_id, proposal.readable_name)
        if normalized_tag:
            products.add_tag(conn, proposal.product_id, normalized_tag)
        if content and proposal.content:
            products.set_content(conn, proposal.product_id, proposal.content.quantity, proposal.content.unit)


def duplicate_candidates(
    conn: sqlite3.Connection, product_ids: Sequence[int] | None = None
) -> list[tuple[Product, Product, float]]:
    universe = products.list_products(conn)
    scope = set(product_ids) if product_ids is not None else {product.id for product in universe}
    scored: dict[tuple[int, int], int] = {}
    for a in universe:
        if a.id not in scope:
            continue
        for b in universe:
            if b.id == a.id:
                continue
            key = (min(a.id, b.id), max(a.id, b.id))
            if key in scored:
                continue
            score = fuzz.token_set_ratio(normalize_text(a.canonical_name), normalize_text(b.canonical_name))
            if score >= DUPLICATE_CANDIDATE_CUTOFF:
                scored[key] = int(score)
    by_id = {product.id: product for product in universe}
    ranked = sorted(scored.items(), key=lambda pair: (-pair[1], pair[0]))[:MAX_DUPLICATE_PAIRS]
    return [(by_id[a_id], by_id[b_id], score / 100) for (a_id, b_id), score in ranked]


def judge_duplicates(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    candidates: Sequence[tuple[Product, Product, float]],
    month: str | None = None,
) -> list[DuplicateCandidate]:
    if not candidates:
        return []
    pairs = [(a.canonical_name, b.canonical_name) for a, b, _ in candidates]
    verdicts = suggestions.suggest_merges(conn, config, client, pairs, month)
    return [
        DuplicateCandidate(product_a=a, product_b=b, text_similarity=similarity, ai=verdict)
        for (a, b, similarity), verdict in zip(candidates, verdicts)
        if verdict is not None and verdict.same_product
    ]
