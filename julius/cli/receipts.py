from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.table import Table
from rich.text import Text

from julius import config
from julius.cli import _review
from julius.cli._common import console, error_console, fail, open_db
from julius.cli._hints import print_hints
from julius.domain.models import ImportResult, PriceRecord, SearchOutcome
from julius.infra import ai_log
from julius.infra.llm_client import HttpLlmClient
from julius.parsers.df import DFReceiptParser
from julius.services import export as export_service, guidance, importing, search as search_service, suggestions

_HIGHLIGHT_STYLE = {"lowest": "green", "highest": "red"}


def import_receipts(
    files: Annotated[list[Path], typer.Argument(help="Arquivos HTML de NFC-e salvos da Receita/DF.")],
    yes: Annotated[bool, typer.Option("--sim", "-y", help="Aplicar as sugestões da IA sem perguntar.")] = False,
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

        merged = _merge(results)
        reviewed = False
        if results and merged.new_product_ids:
            settings = config.load()
            client = HttpLlmClient.from_config(settings)
            if client is not None:
                try:
                    interactive = not yes and _review._is_interactive()
                    reviewed = _review.review_products(
                        conn, settings, client, merged.new_product_ids, assume_yes=yes, interactive=interactive
                    )
                except Exception as error:
                    error_console.print(f"IA: erro ao aplicar sugestões — {error}")
                    reviewed = False
        if results:
            # Hints once per command, not per file: importing a folder must not repeat them.
            print_hints(guidance.after_import(conn, merged, reviewed=reviewed))
    finally:
        conn.close()
    if failed:
        raise typer.Exit(code=1)


def search(
    words: Annotated[
        Optional[list[str]],
        typer.Argument(help="Nome do produto e/ou tag — várias palavras sem aspas, aceita erro de digitação."),
    ] = None,
    tag: Annotated[Optional[str], typer.Option("--tag", help="Filtra por tag marcada em `produtos tag`.")] = None,
    no_tag_detection: Annotated[
        bool,
        typer.Option(
            "--sem-tag", help="Trata tudo como nome de produto, mesmo que uma palavra combine com uma tag conhecida."
        ),
    ] = False,
    limit: Annotated[int, typer.Option("--limite", "-n", min=1, help="Linhas mais recentes por unidade.")] = 20,
) -> None:
    """Mostra o histórico de preços de um produto, agrupado por unidade."""
    words = words or []
    if not words and tag is None:
        raise typer.BadParameter("Informe um termo de busca ou --tag.")
    settings = config.load()
    conn = open_db()
    try:
        if no_tag_detection or tag is not None:
            term = " ".join(words) or None
            outcome = SearchOutcome(tuple(search_service.search_prices(conn, term=term, tag=tag, limit=limit)), term, tag)
        else:
            outcome = search_service.search_free_text(conn, words, tag=None, limit=limit)
        records = list(outcome.records)
        hints = guidance.after_search(conn, outcome.term, outcome.tag, records)
        used_ai_fallback = False
        if not records and outcome.term is not None and outcome.tag is None:
            fallback_records, fallback_hints = _ai_fallback(conn, outcome.term, limit)
            if fallback_records:
                records, hints, used_ai_fallback = fallback_records, fallback_hints, True
        ai_log.append(
            settings.query_log_path,
            {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "words": words,
                "tag_explicit": tag,
                "detected_tag": outcome.detected_tag,
                "term_used": outcome.term,
                "tag_used": outcome.tag,
                "result_count": len(records),
                "ai_fallback": used_ai_fallback,
            },
        )
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


def _ai_fallback(conn, term: str, limit: int) -> tuple[list[PriceRecord], list]:
    """consultar never calls the AI when the deterministic search already found something."""
    settings = config.load()
    client = HttpLlmClient.from_config(settings)
    if client is None or not suggestions.is_available(conn, settings):
        return [], []
    ids = suggestions.match_products(conn, settings, client, term, search_service.catalog_for_matching(conn))
    if not ids:
        return [], []
    records = search_service.records_for_products(conn, ids, limit)
    return records, guidance.after_ai_fallback(records)


def _merge(results: list[ImportResult]) -> ImportResult:
    return ImportResult(
        new_items=sum(result.new_items for result in results),
        existing_items=sum(result.existing_items for result in results),
        new_product_ids=tuple(product_id for result in results for product_id in result.new_product_ids),
    )


def _money(value: float) -> str:
    return f"R$ {value:.2f}".replace(".", ",")


def _store_cell(record: PriceRecord) -> str | Text:
    if not record.store_address:
        return record.store_nickname
    return Text.assemble(record.store_nickname, "\n", (record.store_address, "dim"))


def _table(unit: str, records: list[PriceRecord]) -> Table:
    per_content_units = {r.content_unit for r in records if r.price_per_content is not None}
    table = Table(title=f"Preços por {unit}")
    for column in ("Data", "Produto", "Mercado", "Preço"):
        table.add_column(column)
    if per_content_units:
        (only_unit,) = per_content_units if len(per_content_units) == 1 else (None,)
        table.add_column(f"Por {only_unit}" if only_unit else "Por conteúdo")
    for record in records:
        row = [record.purchased_at[:10], record.canonical_name, _store_cell(record), _money(record.unit_price)]
        if per_content_units:
            row.append("" if record.price_per_content is None else _money(record.price_per_content))
        table.add_row(*row, style=_HIGHLIGHT_STYLE.get(record.highlight or ""))
    return table
