from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.table import Table
from rich.text import Text

from julius import config
from julius.cli import _review, stores as stores_cli
from julius.cli._common import (
    HIGHLIGHT_STYLE,
    br_date,
    console,
    date_cell,
    error_console,
    fail,
    money,
    open_db,
    relative_age,
)
from julius.cli._hints import print_hints
from julius.domain.comparison_basis import comparison_basis
from julius.domain.models import ImportResult, PriceExtreme, PriceRecord, SearchOutcome
from julius.infra import ai_log, receipt_files
from julius.infra.llm_client import HttpLlmClient
from julius.parsers.df import DFReceiptParser
from julius.services import (
    catalog,
    comparison as comparison_service,
    export as export_service,
    guidance,
    importing,
    search as search_service,
    suggestions,
)

_WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
MAX_SIGNAL_LINES = 5


def import_receipts(
    files: Annotated[
        Optional[list[Path]],
        typer.Argument(
            help="Arquivos HTML de NFC-e salvos da Receita/DF. Sem argumento, importa os HTML da pasta de entrada."
        ),
    ] = None,
    yes: Annotated[bool, typer.Option(
            "--sim",
            "-y",
            help="Não perguntar nada; conteúdo que a IA não soube fica pendente para a próxima revisão.",
        )] = False,
) -> None:
    """Importa um ou mais recibos NFC-e para a base de preços."""
    settings = config.load()
    if not files:
        files = _inbox_files(settings.inbox_path)
        if files is None:
            return
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
            filed = _archive(path, settings, result)
            console.print(f"{path.name}: {result.new_items} itens novos, {result.existing_items} já existiam{filed}")
            results.append(result)

        merged = _merge(results)
        if results:
            # Before the product review below, and independent of it: naming a store touches no
            # product, and the documented ordering there (review assigns `kind`, then the extremes
            # signal reads it) is left exactly as it was. Every unnamed store is named, not only
            # this import's: a store the user cannot recognise is worth naming whenever it is seen.
            _name_stores(conn, settings)
        reviewed = False
        if results and merged.new_product_ids:
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
            # Order matters: the review above is what assigns the kind, so the signal below can
            # compare across stores instead of falling back to the product's own history.
            _print_new_extremes(conn, [result.access_key for result in results if result.access_key])
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
        group = [record for record in records if record.unit == unit]
        console.print(_table(unit, group))
        _print_cheapest_per_content(group)
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


def _inbox_files(inbox_path: Path) -> list[Path] | None:
    """The HTML files waiting in the inbox, or None (with a message) when there is nothing to do.

    `glob`, never `rglob`: it is the non-recursion that makes an archived receipt disappear from
    the scan, so `julius importar` means "import what is new".
    """
    if not inbox_path.is_dir():
        console.print("A pasta de entrada não existe. Crie com: make inbox")
        return None
    files = sorted(inbox_path.glob("*.html"))
    if not files:
        console.print(f"Nada para importar em {inbox_path}.")
        return None
    return files


def _archive(path: Path, settings, result: ImportResult) -> str:
    """Only runs after a successful import, so a file that failed stays where it is."""
    try:
        archived = receipt_files.archive(
            path, settings.archive_path, purchased_at=result.purchased_at, access_key=result.access_key
        )
    except (OSError, ValueError) as error:
        error_console.print(f"{path.name}: importado, mas não foi possível arquivar — {error}")
        return ""
    # The `<stem>_files` sidecar is left in place on purpose: deleting it is the system's only
    # destructive step and is still pending the user's decision (receipt_files.discard_sidecar).
    return f" · arquivado como {archived.name}"


def _print_new_extremes(conn, access_keys: list[str]) -> None:
    """Nothing to report prints nothing: silence is the right answer when there is no news."""
    extremes = comparison_service.new_extremes(conn, access_keys)
    if not extremes:
        return
    console.print("Nesta compra:")
    for extreme in extremes[:MAX_SIGNAL_LINES]:
        console.print(f"  {_extreme_line(extreme)}", style=HIGHLIGHT_STYLE.get(extreme.highlight, ""))
    if len(extremes) > MAX_SIGNAL_LINES:
        console.print(f"  +{len(extremes) - MAX_SIGNAL_LINES} mais")


def _extreme_line(extreme: PriceExtreme) -> str:
    arrow = "↓" if extreme.highlight == "lowest" else "↑"
    verdict = "menor preço já pago" if extreme.highlight == "lowest" else "maior preço já pago"
    if extreme.basis == "price_per_content":
        suffix = f"/{extreme.content_unit} (por conteúdo)"
    else:
        suffix = f"/{extreme.unit}"
    # Naming the beaten product is the whole point when the scope is a kind: "menor preço já pago"
    # over `vinho` compared two different wines. Same name means it beat itself, so saying it twice
    # is noise — that is the common case, a product bought again cheaper than last time.
    beaten = (
        f" ({extreme.previous_product_name})"
        if extreme.previous_product_name and extreme.previous_product_name != extreme.product_name
        else ""
    )
    # Separator, not parentheses: `previous` goes inside parentheses below, and nesting reads badly.
    when = f"{br_date(extreme.previous_at)} · {relative_age(extreme.previous_at)}"
    previous = f"era {money(extreme.previous_price)}{beaten} em {extreme.previous_store}, {when}"
    return f"{arrow} {extreme.product_name}  {money(extreme.price)}{suffix}  {verdict} ({previous})"


def _weekday(purchased_at: str) -> str:
    try:
        return _WEEKDAYS[datetime.fromisoformat(purchased_at).weekday()]
    except ValueError:
        return ""


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


def _store_cell(record: PriceRecord) -> str | Text:
    if not record.store_address:
        return record.store_nickname
    return Text.assemble(record.store_nickname, "\n", (record.store_address, "dim"))


_CONTENT_WORDS = {"L": "litro", "KG": "quilo", "UN": "unidade"}


def _print_cheapest_per_content(records: list[PriceRecord]) -> None:
    """States the ordering the table already computed, instead of leaving the user to read the
    column. Not a verdict on the price itself: only which package of what was bought is cheaper."""
    basis, participants = comparison_basis(records)
    if basis != "price_per_content" or len(participants) < 2:
        return
    ranked = sorted((records[i] for i in participants), key=lambda record: record.price_per_content or 0.0)
    cheapest, dearest = ranked[0], ranked[-1]
    if cheapest.price_per_content == dearest.price_per_content:
        return
    word = _CONTENT_WORDS.get(cheapest.content_unit or "", "unidade")
    # "contra" instead of an article: product names have any gender and no rule fits all.
    console.print(
        f"Mais barato por {word}: {cheapest.canonical_name} a {money(cheapest.price_per_content)}/"
        f"{cheapest.content_unit} — contra {money(dearest.price_per_content)}/{dearest.content_unit} "
        f"de {dearest.canonical_name}.",
        style="dim",
    )


def _table(unit: str, records: list[PriceRecord]) -> Table:
    per_content_units = {r.content_unit for r in records if r.price_per_content is not None}
    table = Table(title=f"Preços por {unit}")
    for column in ("Data", "Dia", "Produto", "Mercado", "Preço"):
        table.add_column(column)
    if per_content_units:
        (only_unit,) = per_content_units if len(per_content_units) == 1 else (None,)
        table.add_column(f"Por {only_unit}" if only_unit else "Por conteúdo")
    for record in records:
        row = [
            date_cell(record.purchased_at),
            _weekday(record.purchased_at),
            record.canonical_name,
            _store_cell(record),
            money(record.unit_price),
        ]
        if per_content_units:
            row.append("" if record.price_per_content is None else money(record.price_per_content))
        table.add_row(*row, style=HIGHLIGHT_STYLE.get(record.highlight or ""))
    return table


def _name_stores(conn, settings) -> None:
    """Never lets a naming problem fail an import that already wrote its prices.

    The registry only — no AI client is passed. Reimporting a receipt must not spend budget, and a
    store nothing can name stays pending, so an AI call here would repeat on every import for as
    long as it stays unknown. The paid source runs where the user asks for it: `mercados revisar`.
    """
    try:
        namings = catalog.name_stores(conn, settings, None)
    except Exception as error:
        error_console.print(f"Apelidos: erro ao consultar nome fantasia — {error}")
        return
    if not namings:
        return
    stores_cli.log_namings(settings, namings)
    console.print(f"{len(namings)} mercado(s) ganharam apelido:")
    stores_cli.print_namings(namings)
