"""Comparing prices between stores, by comparison group.

Never an index and never an average: the answer is one group at a time, with the number of
groups and the date range that back it — measured, the Assaí receipts are all from 04/09 and the
FL 3 Costa ones from 12-16/09, so part of any difference can be the month, not the store.
"""

from __future__ import annotations

import sqlite3

from julius.domain.comparison_basis import basis_value, comparison_basis
from julius.domain.models import KindComparison, PriceRecord, StoreComparison, StorePrice
from julius.repositories import prices, products


def compare_stores(conn: sqlite3.Connection) -> StoreComparison:
    """One KindComparison per (kind, unit) observed in at least 2 stores. A store's price for a
    group is the cheapest it charged, with that observation's date: the price-shopping question
    is "what would I pay there", so the cheapest available is the fair representative."""
    typed = [product.id for product in products.list_products(conn) if product.kind is not None]
    if not typed:
        return StoreComparison((), "", "")
    # ponytail: scans every price row of typed products (132 today). SQL aggregation only if the
    # database grows orders of magnitude.
    groups: dict[tuple[str, str], list[PriceRecord]] = {}
    for record in prices.prices_for_products(conn, typed):
        if record.kind is not None:
            groups.setdefault((record.kind, record.unit), []).append(record)

    comparisons: list[KindComparison] = []
    used_dates: list[str] = []
    for key in sorted(groups):
        group = groups[key]
        basis, participants = comparison_basis(group)
        priced = [(value, group[index]) for index in participants if (value := basis_value(group[index], basis)) is not None]
        cheapest: dict[str, tuple[float, str]] = {}
        for value, record in priced:
            current = cheapest.get(record.store_nickname)
            if current is None or value < current[0] or (value == current[0] and record.purchased_at > current[1]):
                cheapest[record.store_nickname] = (value, record.purchased_at)
        if len(cheapest) < 2:
            continue
        entries = tuple(
            StorePrice(store, value, purchased_at)
            for store, (value, purchased_at) in sorted(cheapest.items(), key=lambda item: (item[1][0], item[0]))
        )
        kind, unit = key
        content_unit = priced[0][1].content_unit if basis == "price_per_content" else None
        comparisons.append(KindComparison(kind, unit, basis, content_unit, entries))  # type: ignore[arg-type]
        used_dates += [entry.purchased_at for entry in entries]

    if not comparisons:
        return StoreComparison((), "", "")
    return StoreComparison(tuple(comparisons), min(used_dates), max(used_dates))
