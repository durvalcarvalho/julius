from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from rapidfuzz import fuzz

from julius.config import Config
from julius.domain.models import AppliedAction, ContentSuggestion, DuplicateCandidate, Product, ProductProposal
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
    known_kinds = products.all_kinds(conn)
    enrichment = suggestions.enrich_products(
        conn, config, client, [product for _, product in found], known, known_kinds
    )
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
                kind=_proposed_kind(product, item.kind),
            )
        )
    return proposals


def _proposed_kind(product: Product, proposed: str | None) -> str | None:
    """The AI never overwrites a kind already chosen — same discipline as has_raw_name for names."""
    return None if product.kind is not None else proposed


def apply(
    conn: sqlite3.Connection, proposal: ProductProposal, *, tag: str | None, content: bool, kind: bool
) -> list[AppliedAction]:
    normalized_tag = None
    if tag:
        normalized_tag = tag.strip().lower()
        if not normalized_tag:
            raise ValueError("tag must not be blank")
    before = products.get_product(conn, proposal.product_id)
    if before is None:
        raise LookupError(f"product {proposal.product_id} not found")
    product_id = proposal.product_id
    actions: list[AppliedAction] = []
    with conn:
        if proposal.readable_name and proposal.readable_name != before.canonical_name:
            products.rename_product(conn, product_id, proposal.readable_name)
            actions.append(AppliedAction(product_id, "name", before.canonical_name, proposal.readable_name))
        if normalized_tag and normalized_tag not in before.tags:
            products.add_tag(conn, product_id, normalized_tag)
            actions.append(AppliedAction(product_id, "tag", None, normalized_tag))
        if content and proposal.content:
            after_content = _content_text(proposal.content)
            before_content = (
                None
                if before.content_quantity is None
                else _content_text(ContentSuggestion(before.content_quantity, before.content_unit))  # type: ignore[arg-type]
            )
            if after_content != before_content:
                products.set_content(conn, product_id, proposal.content.quantity, proposal.content.unit)
                actions.append(AppliedAction(product_id, "content", before_content, after_content))
        if kind and proposal.kind:
            products.set_kind(conn, product_id, proposal.kind)
            # Read back: set_kind may reuse an existing spelling, and the log must say what was stored.
            stored = products.get_product(conn, product_id)
            if stored is not None and stored.kind != before.kind:
                actions.append(AppliedAction(product_id, "kind", before.kind, stored.kind))
    return actions


def _content_text(content: ContentSuggestion) -> str:
    return f"{content.quantity:g} {content.unit}"


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
