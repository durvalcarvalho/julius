from __future__ import annotations

from collections import Counter
from typing import Annotated

import typer
from rich.table import Table

from julius.cli._common import HIGHLIGHT_STYLE, console, fail, money, open_db
from julius.domain.models import KindComparison, StoreComparison
from julius.domain.normalization import digits_only
from julius.services import catalog, comparison as comparison_service

app = typer.Typer()


@app.command("listar")
def list_stores() -> None:
    """Lista os mercados já importados, com CNPJ, razão social e apelido."""
    conn = open_db()
    try:
        stores = catalog.list_stores(conn)
    finally:
        conn.close()
    if not stores:
        console.print("Nenhum mercado importado ainda.")
        return
    table = Table("CNPJ", "Razão social", "Apelido", "Endereço")
    for store in stores:
        table.add_row(store.cnpj, store.legal_name, store.nickname, store.address or "")
    console.print(table)


@app.command("renomear")
def rename_store(
    cnpj: Annotated[str, typer.Argument(help="CNPJ do mercado, formatado ou só dígitos.")],
    nickname: Annotated[str, typer.Argument(help="Apelido pelo qual você reconhece o mercado.")],
) -> None:
    """Dá um apelido legível a um mercado (a razão social do cupom raramente ajuda)."""
    cnpj = digits_only(cnpj)
    conn = open_db()
    try:
        catalog.rename_store(conn, cnpj, nickname)
    except (ValueError, LookupError) as error:
        fail(str(error))
    finally:
        conn.close()
    console.print(f"Mercado {cnpj} agora é '{nickname.strip()}'.")


@app.command("comparar")
def compare_stores() -> None:
    """Compara o preço dos mesmos tipos de produto entre os mercados."""
    conn = open_db()
    try:
        comparison = comparison_service.compare_stores(conn)
        products = catalog.list_products(conn)
    finally:
        conn.close()
    typed = sum(1 for product in products if product.kind)
    if not comparison.comparisons:
        if not typed:
            console.print("Nenhum produto tem tipo ainda. Rode: julius produtos revisar")
        else:
            console.print("Nenhum tipo de produto foi comprado em dois mercados ainda — sem base para comparar.")
            # Coverage, not existence: one typed product out of a hundred used to silence this,
            # and a half-curated catalogue is the likeliest reason there is nothing to compare.
            if typed < len(products):
                missing = len(products) - typed
                console.print(
                    f"{missing} dos {len(products)} produtos ainda não têm tipo. Rode: julius produtos revisar",
                    style="dim",
                )
        return

    labels = _labels(comparison)
    for group in comparison.comparisons:
        console.print(_comparison_table(group, labels))

    appearances = Counter(entry.store_cnpj for group in comparison.comparisons for entry in group.entries)
    wins = Counter(group.entries[0].store_cnpj for group in comparison.comparisons)
    width = max(len(labels[cnpj]) for cnpj in appearances)
    for cnpj, total in sorted(appearances.items(), key=lambda item: (-wins[item[0]] / item[1], labels[item[0]])):
        console.print(f"{labels[cnpj].ljust(width)}  mais barato em {wins[cnpj]} de {total} {_plural(total)}")

    first, last = comparison.first_purchase, comparison.last_purchase
    count = len(comparison.comparisons)
    console.print(f"base: {count} {_plural(count)} · {_day_month(first)} a {_day_month(last)}")
    console.print("Período largo: parte da diferença pode ser variação de preço no mês, não o mercado.", style="dim")


def _plural(count: int) -> str:
    return "grupo" if count == 1 else "grupos"


def _day_month(purchased_at: str) -> str:
    return f"{purchased_at[8:10]}/{purchased_at[5:7]}"


def _labels(comparison: StoreComparison) -> dict[str, str]:
    """A name per CNPJ. Two branches of one chain carry the same nickname until the user renames
    them, and two identical rows in a table is the one thing worse than dropping the group — so a
    shared nickname gets its CNPJ appended. `julius mercados listar` shows which address is which."""
    by_nickname: dict[str, set[str]] = {}
    for group in comparison.comparisons:
        for entry in group.entries:
            by_nickname.setdefault(entry.store_nickname, set()).add(entry.store_cnpj)
    return {
        entry.store_cnpj: (
            f"{entry.store_nickname} · {entry.store_cnpj}"
            if len(by_nickname[entry.store_nickname]) > 1
            else entry.store_nickname
        )
        for group in comparison.comparisons
        for entry in group.entries
    }


def _comparison_table(group: KindComparison, labels: dict[str, str]) -> Table:
    if group.basis == "price_per_content":
        basis = f"por {group.content_unit} (por conteúdo)"
    else:
        basis = f"por {group.unit}"
    table = Table("Mercado", "Preço", "Data", title=f"{group.kind} · {basis}")
    cheapest, dearest = group.entries[0].price, group.entries[-1].price
    for entry in group.entries:
        highlight = "lowest" if entry.price == cheapest else "highest" if entry.price == dearest else None
        table.add_row(labels[entry.store_cnpj], money(entry.price), entry.purchased_at[:10], style=HIGHLIGHT_STYLE.get(highlight or ""))
    return table

