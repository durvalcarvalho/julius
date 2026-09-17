"""Comparing prices between stores, by comparison group.

Never an index and never an average: the answer is one group at a time, with the number of
groups and the date range that back it — measured, the Assaí receipts are all from 04/09 and the
FL 3 Costa ones from 12-16/09, so part of any difference can be the month, not the store.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from julius.domain.comparison_basis import basis_value, comparison_basis
from julius.domain.models import KindComparison, PriceExtreme, PriceRecord, StoreComparison, StorePrice
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
        # Keyed by CNPJ, never by nickname: two branches of one chain are distinct stores with
        # distinct prices, and they share a nickname until the user renames them (measured: both
        # Dona de Casa branches sell the same bag, and the group was being dropped as single-store).
        cheapest: dict[str, tuple[float, PriceRecord]] = {}
        for value, record in priced:
            current = cheapest.get(record.store_cnpj)
            if current is None or value < current[0] or (value == current[0] and record.purchased_at > current[1].purchased_at):
                cheapest[record.store_cnpj] = (value, record)
        if len(cheapest) < 2:
            continue
        entries = tuple(
            StorePrice(record.store_nickname, value, record.purchased_at, cnpj)
            for cnpj, (value, record) in sorted(cheapest.items(), key=lambda item: (item[1][0], item[1][1].store_nickname, item[0]))
        )
        kind, unit = key
        content_unit = priced[0][1].content_unit if basis == "price_per_content" else None
        comparisons.append(KindComparison(kind, unit, basis, content_unit, entries))  # type: ignore[arg-type]
        used_dates += [entry.purchased_at for entry in entries]

    if not comparisons:
        return StoreComparison((), "", "")
    return StoreComparison(tuple(comparisons), min(used_dates), max(used_dates))


def new_extremes(conn: sqlite3.Connection, access_keys: Sequence[str]) -> list[PriceExtreme]:
    """Items in the given receipts that set a new low or high within their comparison group.

    "Previous" excludes every row of `access_keys`, so the comparison is never circular, and
    tying your own record is not news: only a strict new extreme is reported.
    """
    keys = set(access_keys)
    if not keys:
        return []
    all_ids = [product.id for product in products.list_products(conn)]
    records = prices.prices_for_products(conn, all_ids)
    extremes: list[PriceExtreme] = []
    for record in records:
        if record.access_key not in keys:
            continue
        if record.kind is not None:
            scope_name = record.kind
            scope_rows = [row for row in records if row.kind == record.kind and row.unit == record.unit]
        else:
            # Degraded scope, not a lazy fallback: it is what makes the signal work before the
            # kind curation reaches the whole catalogue.
            scope_name = record.canonical_name
            scope_rows = [row for row in records if row.product_id == record.product_id and row.unit == record.unit]
        basis, participants = comparison_basis(scope_rows)
        own_index = next(index for index, row in enumerate(scope_rows) if row is record)
        if own_index not in participants:
            continue
        value = basis_value(record, basis)
        history = [
            (candidate, scope_rows[index])
            for index in participants
            if scope_rows[index].access_key not in keys
            and (candidate := basis_value(scope_rows[index], basis)) is not None
        ]
        if value is None or not history:
            continue
        lowest = min(history, key=lambda item: item[0])
        highest = max(history, key=lambda item: item[0])
        if value < lowest[0]:
            highlight, (previous_value, previous_row) = "lowest", lowest
        elif value > highest[0]:
            highlight, (previous_value, previous_row) = "highest", highest
        else:
            continue
        extremes.append(
            PriceExtreme(
                product_name=record.canonical_name,
                store_nickname=record.store_nickname,
                unit=record.unit,
                price=value,
                highlight=highlight,  # type: ignore[arg-type]
                basis=basis,
                content_unit=record.content_unit if basis == "price_per_content" else None,
                previous_price=previous_value,
                previous_store=previous_row.store_nickname,
                previous_at=previous_row.purchased_at,
                scope=scope_name,
            )
        )
    # Lowest first, then the strongest news: the biggest relative move against the previous price.
    return sorted(extremes, key=lambda e: (e.highlight != "lowest", -abs(e.price - e.previous_price) / e.previous_price))
