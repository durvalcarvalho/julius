from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.table import Table

from julius.cli._common import console, error_console, fail, open_db
from julius.cli._hints import print_hints
from julius.domain.models import ImportResult, PriceRecord
from julius.parsers.df import DFReceiptParser
from julius.services import export as export_service, guidance, importing, search as search_service

_HIGHLIGHT_STYLE = {"lowest": "green", "highest": "red"}


def import_receipts(
    files: Annotated[list[Path], typer.Argument(help="Arquivos HTML de NFC-e salvos da Receita/DF.")],
) -> None:
    """Importa um ou mais recibos NFC-e para a base de preços."""
    parser = DFReceiptParser()
    failed = False
    results: list[ImportResult] = []
    conn = open_db()
    try:
        for path in files:
            try:
                result = importing.import_receipt(conn, path, parser)
            except (FileNotFoundError, ValueError) as error:
                failed = True
                error_console.print(f"{path.name}: erro — {error}")
                print_hints(guidance.for_import_error(error, path), to_stderr=True)
                continue
            console.print(f"{path.name}: {result.new_items} itens novos, {result.existing_items} já existiam")
            results.append(result)
        if results:
            # Hints once per command, not per file: importing a folder must not repeat them.
            print_hints(guidance.after_import(conn, _merge(results)))
    finally:
        conn.close()
    if failed:
        raise typer.Exit(code=1)


def search(
    term: Annotated[Optional[str], typer.Argument(help="Nome (ou parte) do produto; aceita erro de digitação.")] = None,
    tag: Annotated[Optional[str], typer.Option("--tag", help="Filtra por tag marcada em `produtos tag`.")] = None,
    limit: Annotated[int, typer.Option("--limite", "-n", min=1, help="Linhas mais recentes por unidade.")] = 20,
) -> None:
    """Mostra o histórico de preços de um produto, agrupado por unidade."""
    if term is None and tag is None:
        raise typer.BadParameter("Informe um termo de busca ou --tag.")
    conn = open_db()
    try:
        records = search_service.search_prices(conn, term=term, tag=tag, limit=limit)
        hints = guidance.after_search(conn, term, tag, records)
    finally:
        conn.close()
    if not records and not hints:
        console.print("Nenhum resultado.")
    for unit in sorted({record.unit for record in records}):
        console.print(_table(unit, [record for record in records if record.unit == unit]))
    print_hints(hints)


def export(
    output: Annotated[Path, typer.Option("--saida", "-o", help="Caminho do CSV de saída.")] = Path("julius-export.csv"),
) -> None:
    """Exporta todos os preços para um CSV (separador ';')."""
    conn = open_db()
    try:
        count = export_service.export_csv(conn, output)
    finally:
        conn.close()
    console.print(f"{count} linhas exportadas para {output}")


def _merge(results: list[ImportResult]) -> ImportResult:
    return ImportResult(
        new_items=sum(result.new_items for result in results),
        existing_items=sum(result.existing_items for result in results),
        new_product_ids=tuple(product_id for result in results for product_id in result.new_product_ids),
    )


def _money(value: float) -> str:
    return f"R$ {value:.2f}".replace(".", ",")


def _table(unit: str, records: list[PriceRecord]) -> Table:
    per_content_units = {r.content_unit for r in records if r.price_per_content is not None}
    table = Table(title=f"Preços por {unit}")
    for column in ("Data", "Produto", "Mercado", "Preço"):
        table.add_column(column)
    if per_content_units:
        (only_unit,) = per_content_units if len(per_content_units) == 1 else (None,)
        table.add_column(f"Por {only_unit}" if only_unit else "Por conteúdo")
    for record in records:
        row = [record.purchased_at[:10], record.canonical_name, record.store_nickname, _money(record.unit_price)]
        if per_content_units:
            row.append("" if record.price_per_content is None else _money(record.price_per_content))
        table.add_row(*row, style=_HIGHLIGHT_STYLE.get(record.highlight or ""))
    return table
