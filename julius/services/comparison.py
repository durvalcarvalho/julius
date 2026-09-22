"""Comparing prices between stores, by comparison group.

Never an index and never an average: the answer is one group at a time, with the number of
groups and the date range that back it — measured, the Assaí receipts are all from 04/09 and the
FL 3 Costa ones from 12-16/09, so part of any difference can be the month, not the store.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import replace

from julius.domain.comparison_basis import basis_value, comparison_basis
from julius.domain.formatting import store_labels
from julius.domain.models import (
    KindComparison,
    PriceCheck,
    PriceExtreme,
    PriceRecord,
    SaleUnit,
    ShoppingVerdict,
    StoreComparison,
    StorePrice,
)
from julius.repositories import prices, products


def compare_stores(conn: sqlite3.Connection, kinds: Sequence[str] | None = None) -> StoreComparison:
    """One KindComparison per (kind, unit) observed in at least 2 stores. A store's price for a
    group is the cheapest it charged, with that observation's date: the price-shopping question
    is "what would I pay there", so the cheapest available is the fair representative.

    `kinds`, when given a non-empty sequence, restricts the comparison to those kinds -- this is
    what lets the bot compare only a shopping list instead of every kind ever bought (measured
    incident: 16 kinds narrated at once truncated the persona's reply twice, `ai_calls.jsonl`
    2026-09-19T17:42:52). `None` or empty is exactly today's behaviour, unchanged: `julius
    mercados comparar` (the CLI) never passes `kinds`."""
    wanted = set(kinds) if kinds else None
    typed = [
        product.id
        for product in products.list_products(conn)
        if product.kind is not None and (wanted is None or product.kind in wanted)
    ]
    if not typed:
        return StoreComparison((), "", "")
    # ponytail: scans every price row of typed products (132 today). SQL aggregation only if the
    # database grows orders of magnitude.
    groups: dict[tuple[str, str], list[PriceRecord]] = {}
    # Counted by kind, never by `len(groups)`: those are keyed by (kind, unit), and one kind sold
    # both by weight and by package is two keys but one kind (87 kinds against 89 keys today).
    stores_per_kind: dict[str, set[str]] = {}
    for record in prices.prices_for_products(conn, typed):
        if record.kind is not None:
            groups.setdefault((record.kind, record.unit), []).append(record)
            stores_per_kind.setdefault(record.kind, set()).add(record.store_cnpj)
    coverage = (len(stores_per_kind), sum(1 for cnpjs in stores_per_kind.values() if len(cnpjs) == 1))

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
            StorePrice(record.store_nickname, value, record.purchased_at, record.canonical_name, cnpj)
            for cnpj, (value, record) in sorted(cheapest.items(), key=lambda item: (item[1][0], item[1][1].store_nickname, item[0]))
        )
        kind, unit = key
        content_unit = priced[0][1].content_unit if basis == "price_per_content" else None
        comparisons.append(KindComparison(kind, unit, basis, content_unit, entries))  # type: ignore[arg-type]
        used_dates += [entry.purchased_at for entry in entries]

    if not comparisons:
        return StoreComparison((), "", "", *coverage)
    return StoreComparison(tuple(comparisons), min(used_dates), max(used_dates), *coverage)


def _assemble_verdict(labels: dict[str, str], kind_winner: dict[str, str]) -> ShoppingVerdict:
    """Counts wins per store from an already-decided kind -> winning-CNPJ map, and turns that into
    a winner (or a tie of winners) plus a single runner-up for everything left over. Shared by the
    plain per-kind tally and the category-capped one (Decisão 5, docs/design/shopping-verdict-shape.md)
    -- they differ only in how `kind_winner` is built, never in how it is summarized."""
    wins: dict[str, int] = {}
    for cnpj in kind_winner.values():
        wins[cnpj] = wins.get(cnpj, 0) + 1
    top = max(wins.values())
    winner_cnpjs = {cnpj for cnpj, count in wins.items() if count == top}
    won_kinds = tuple(kind for kind, cnpj in kind_winner.items() if cnpj in winner_cnpjs)
    leftover = [kind for kind, cnpj in kind_winner.items() if cnpj not in winner_cnpjs]
    runner_up_store: str | None = None
    runner_up_kinds: tuple[str, ...] = ()
    if leftover:
        runner_up_wins: dict[str, int] = {}
        for kind in leftover:
            cnpj = kind_winner[kind]
            runner_up_wins[cnpj] = runner_up_wins.get(cnpj, 0) + 1
        # ponytail: a tie for second place is not broken separately -- it keeps whichever CNPJ
        # sorts first. The primary recommendation (winner_stores) already handles ties honestly;
        # this is secondary information, and no real case has shown this simplification to matter.
        best_runner_up = max(sorted(runner_up_wins), key=lambda cnpj: runner_up_wins[cnpj])
        runner_up_store = labels[best_runner_up]
        runner_up_kinds = tuple(kind for kind in leftover if kind_winner[kind] == best_runner_up)
    return ShoppingVerdict(
        total_items=len(kind_winner),
        winner_stores=tuple(labels[cnpj] for cnpj in sorted(winner_cnpjs, key=lambda cnpj: labels[cnpj])),
        won_kinds=won_kinds,
        runner_up_store=runner_up_store,
        runner_up_kinds=runner_up_kinds,
    )


def _category_winners(comparison: StoreComparison, category_of: Mapping[str, str]) -> dict[str, str]:
    """One winning CNPJ per category (the store that won the most kinds of that category), capped
    to at most 2 distinct stores across all categories -- see docs/design/shopping-verdict-shape.md,
    Decisão 5. A category with a winner outside the top 2 is reassigned to whichever of the two
    finalists won more of that category's own kinds (never to the excluded third store, even if it
    was technically cheaper): going to a 3rd market for one minor category is the exact outcome
    RF6 rejects."""
    category_wins: dict[str, dict[str, int]] = {}
    for group in comparison.comparisons:
        category = category_of.get(group.kind, "outros")
        wins = category_wins.setdefault(category, {})
        cnpj = group.entries[0].store_cnpj
        wins[cnpj] = wins.get(cnpj, 0) + 1
    # Tie -> lowest CNPJ, same idiom as the runner-up tie-break in _assemble_verdict.
    category_winner = {category: max(sorted(wins), key=lambda cnpj: wins[cnpj]) for category, wins in category_wins.items()}

    kinds_per_store: dict[str, int] = {}
    for category, cnpj in category_winner.items():
        kinds_per_store[cnpj] = kinds_per_store.get(cnpj, 0) + len(
            [g for g in comparison.comparisons if category_of.get(g.kind, "outros") == category]
        )
    if len(kinds_per_store) > 2:
        finalists = set(sorted(kinds_per_store, key=lambda cnpj: (-kinds_per_store[cnpj], cnpj))[:2])
        for category, cnpj in list(category_winner.items()):
            if cnpj not in finalists:
                wins = category_wins[category]
                category_winner[category] = max(sorted(finalists), key=lambda candidate: wins.get(candidate, 0))
    return category_winner


def shopping_verdict(
    comparison: StoreComparison, category_of: Mapping[str, str] | None = None
) -> ShoppingVerdict | None:
    """Turns a StoreComparison into a single recommendation: who to buy from, and where the
    leftover items are cheaper -- the same tally `bot/render.py::render_comparison` already does
    for the raw table, but ending in a winner and a runner-up instead of a row per store.

    Tallied by store_cnpj, never store_nickname: two branches of one chain can share a nickname
    (see test_compare_stores_keeps_two_branches_that_share_a_nickname) and store_labels() is what
    turns a shared nickname back into two distinct labels.

    `category_of` (kind -> category name, e.g. `products.kind_categories()`), when given, groups
    whole categories under at most 2 stores instead of tallying wins kind by kind -- never splits
    a category (like "hortifruti") between the winner and the runner-up. `None`, the default and
    what every caller before this one still gets (including `julius mercados comparar`, which
    never scopes to a shopping list), keeps the original per-kind tally, unrestricted in how many
    stores it can name."""
    if not comparison.comparisons:
        return None
    labels = store_labels(comparison)
    if category_of is None:
        kind_winner = {group.kind: group.entries[0].store_cnpj for group in comparison.comparisons}
    else:
        category_winner = _category_winners(comparison, category_of)
        kind_winner = {
            group.kind: category_winner[category_of.get(group.kind, "outros")] for group in comparison.comparisons
        }
    return _assemble_verdict(labels, kind_winner)


WORTH_IT_THRESHOLD_REAIS = 15.0
"""Above this amount in reais (the R$ gap over the cheapest price ever registered, times how much
the person intends to buy), switching stores is judged worth it (see docs/design/
quantity-aware-verdict.md, Decisão 1). Replaces the old `LIVE_PRICE_TOLERANCE_PCT`: a percentage
gate cannot tell a R$0,02 gap on a R$0,20 bag (10%, never worth asking) from a R$5,00 gap on a
R$35,00 kilo of meat (14%, same band, real money) -- measured on the real catalogue's 17 kinds
with 2+ stores. Only 1 real data point exists (the conversation that opened this design: R$5-10 on
a small purchase "não vale", R$70 on a 14kg one "vale") -- recalibrate as soon as a second real
case exists, same discipline as the constant this one replaces."""

PLAUSIBLE_QTY_MIN = 0.2
PLAUSIBLE_QTY_MAX = 20.0
"""The assumed range of "how much someone might plausibly buy" (kg, L or units alike -- ponytail:
one range for all three, not measured per unit; revisit if a real case, likely a liquid, shows 20
is implausible). Used only to decide whether the gap already settles the verdict at either end of
this range, without asking quantity at all (Decisão 1)."""


def check_price(
    conn: sqlite3.Connection, kind: str, price: float, quantity: float | None = None, unit: SaleUnit | None = None
) -> PriceCheck:
    """Checks a price the person is seeing right now against the cheapest ever registered for
    `kind` -- the one exception this project makes to "never a verdict on an absolute price" (see
    docs/design/shopping-verdict-shape.md, Decisão 4 and RNF2 of the requirements doc). `kind`
    must already be resolved (`search.match_kind`); a term that matches nothing is the caller's
    "unknown_item" to report, not this function's.

    The reference is the lowest price ever paid, full history, same "menor valor já pago"
    semantics `search_prices`' `highlight` already uses -- deliberately NOT `compare_stores`'
    cheapest-per-store collapsing, which answers a different question (what would I pay at EACH
    store, to compare stores fairly). Here there is only one number to report, and the person's
    own framing ("o menor preço que conheço") is exactly "ever, anywhere". A stale reference (an
    old receipt, a store that may have changed since) is not hidden: `reference_at` always rides
    along in the facts/fallback line, so the date is visible and the person judges staleness
    themselves -- same "mostra o dado, deixa a pessoa decidir" rule as the rest of this project.

    Never guesses a unit basis: a `kind` with history in more than one `unit` (real case measured
    against production -- "tomate" has both loose tomatoes by KG and a packaged combo by UN) comes
    back with `reason="ambiguous_unit"` instead of picking one, same discipline as content never
    being inferred from text elsewhere in this project. A `kind` whose only history is different
    UN products with no declared content (comparison_basis finds nothing comparable -- see
    "Preço por conteúdo" in CLAUDE.md) is `reason="no_comparable_basis"`, never mislabelled as "no
    history": there IS history, it just cannot be compared without a content declared first.

    `unit`, when given, filters the history to that sale unit before anything else -- the second
    half of `reason="ambiguous_unit"`, which used to be a dead end: the reason told the caller to
    ask "por peso ou por unidade", but nothing accepted the answer, so a real "por quilo" reply
    from the person (confirmed live, 2026-09-22) just asked the same question again forever. The
    caller resolves the answer to "KG"/"UN" (same vocabulary `PriceRecord.unit`/`ReceiptItem.unit`
    already use) and calls again with `unit` set.

    Real bug found and fixed the same day (2026-09-22, live against the production model): the
    caller (`bot/actions.py::check_price`) let the model pass `quantity` on the very first ask,
    before the person ever said how much -- `deepseek-flash` defaulted to `quantity=1` unprompted,
    skipping `reason="quantity_needed"` (and the question that reason exists to trigger) entirely.
    The fix lives in the action's docstring/prompt discipline, not here: this function still never
    second-guesses whatever `quantity` it receives, same as before.

    Whether the answer needs `quantity` at all is decided by the R$ gap alone, not by `quantity`
    being given (see docs/design/quantity-aware-verdict.md, Decisão 1): a gap so small that it
    never clears `WORTH_IT_THRESHOLD_REAIS` even at `PLAUSIBLE_QTY_MAX`, or so large it already
    clears it at `PLAUSIBLE_QTY_MIN`, is decided immediately -- `quantity`, if given anyway, is
    ignored in those two cases. Only the middle band asks: `quantity=None` there comes back with
    `reason="quantity_needed"` (verdict still undecided, every other fact already filled in, so
    the caller can ask without losing the reference price/store/date); `quantity` given there
    settles it by `gap * quantity` against `WORTH_IT_THRESHOLD_REAIS`."""
    typed = [product.id for product in products.list_products(conn) if product.kind == kind]
    records = prices.prices_for_products(conn, typed) if typed else []
    if unit is not None:
        records = [record for record in records if record.unit == unit]
    empty = PriceCheck(
        kind=kind, verdict=None, informed_price=price, reference_price=None, reference_unit=None,
        reference_store=None, reference_at=None, diff_pct=None, reason="no_history",
    )
    if not records:
        return empty
    if len({record.unit for record in records}) > 1:
        return replace(empty, reason="ambiguous_unit")
    basis, participants = comparison_basis(records)
    priced = [
        (value, records[index])
        for index in participants
        if (value := basis_value(records[index], basis)) is not None
    ]
    if not priced:
        return replace(empty, reason="no_comparable_basis")
    reference_value, reference_record = min(priced, key=lambda item: item[0])
    diff_pct = (price - reference_value) / reference_value * 100
    reference_unit = reference_record.content_unit if basis == "price_per_content" else reference_record.unit
    base = PriceCheck(
        kind=kind,
        verdict=None,
        informed_price=price,
        reference_price=reference_value,
        reference_unit=reference_unit,
        reference_store=reference_record.store_nickname,
        reference_at=reference_record.purchased_at,
        diff_pct=diff_pct,
        reason=None,
    )
    gap = price - reference_value  # direct, never derived back from diff_pct (avoids rounding drift)
    if gap <= 0 or gap * PLAUSIBLE_QTY_MAX <= WORTH_IT_THRESHOLD_REAIS:
        return replace(base, verdict=True)
    if gap * PLAUSIBLE_QTY_MIN >= WORTH_IT_THRESHOLD_REAIS:
        return replace(base, verdict=False)
    if quantity is None:
        return replace(base, reason="quantity_needed")
    return replace(base, verdict=(gap * quantity) <= WORTH_IT_THRESHOLD_REAIS)


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
                previous_product_name=previous_row.canonical_name,
                scope=scope_name,
            )
        )
    # Lowest first, then the strongest news: the biggest relative move against the previous price.
    return sorted(extremes, key=lambda e: (e.highlight != "lowest", -abs(e.price - e.previous_price) / e.previous_price))
